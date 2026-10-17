# SPDX-License-Identifier: GPL-2.0-or-later
"""Production SRC extension checks, called by probe_digitakt_src.py --storage."""
from pathlib import Path
import struct
import tempfile

from elekloader import formats, link
from elekloader.sdk import build

ROOT = Path(__file__).resolve().parents[1]


def probe_storage(stock_path, Machine, call, pc_register):
    import unicorn
    import unicorn.m68k_const as regs

    stock, dev, release = formats.load(str(stock_path))
    image = formats.main_image(stock, dev)
    with tempfile.TemporaryDirectory(prefix='digitakt-src-storage-') as tmp:
        mods = [build.build(str(ROOT / path), str(stock_path), tmp)[1] for path in (
            'mods/core', 'mods/machine-pages', 'tests/fixtures/digitakt-src-parameters',
            'tests/fixtures/digitakt-src-storage',
        )]
        linked = link.link(mods, image)
    assert linked.tables['ev_render_voices'][1] == 0
    m = Machine()
    m.load(linked.image, dev.main_load)
    m.install_isa_patches_scoped(linked.image, dev.main_load)
    lo, hi = linked.layout['ddr']
    offset = linked.layout['run_load'] - dev.main_load
    runtime = linked.image[offset:offset + hi - lo]
    m.load(runtime, lo)
    m.install_isa_patches_scoped(runtime, lo)
    bss_lo, bss_hi = linked.layout['bss']
    m.load(bytes(bss_hi - bss_lo), bss_lo)
    sound, saved, loaded = 0x43000100, 0x43100100, 0x43200100
    for pointer in (sound, saved, loaded):
        m.ensure(pointer)
    nonvolatile = [getattr(regs, 'UC_M68K_REG_' + name)
                   for name in ['D2', 'D3', 'D4', 'D5', 'D6', 'D7',
                                'A2', 'A3', 'A4', 'A5', 'A6']]
    stack = 0x100FFF00
    m.ensure(stack)
    guard = b'\xa5' * 16

    def native(address, args, limit=200_000):
        seeds = [0x12340000 + i for i in range(len(nonvolatile))]
        for register, value in zip(nonvolatile, seeds):
            m.uc.reg_write(register, value)
        result = call(m, address, args, ret_magic=0xDEADBEE0, stack_top=stack, limit=limit)
        assert m.uc.reg_read(pc_register) == 0xDEADBEE0, hex(address)
        assert m.uc.reg_read(regs.UC_M68K_REG_A7) == stack + 4
        assert [m.uc.reg_read(r) for r in nonvolatile] == seeds, hex(address)
        return result

    def protect(pointer, length):
        m.uc.mem_write(pointer - 16, guard)
        m.uc.mem_write(pointer + length, guard)

    def guarded(pointer, length):
        assert bytes(m.uc.mem_read(pointer - 16, 16)) == guard
        assert bytes(m.uc.mem_read(pointer + length, 16)) == guard

    def long_at(address):
        return struct.unpack('>I', m.uc.mem_read(address, 4))[0]

    def put_long(address, value):
        m.uc.mem_write(address, struct.pack('>I', value))

    def initialize(machine=121):
        native(0x40084EF6, [sound, 0, 3])
        m.uc.mem_write(sound + 126, bytes([machine]))

    def load(record):
        m.uc.mem_write(saved, bytes(record))
        m.uc.mem_write(loaded, b'\xcc' * 162)
        protect(loaded, 162)
        result = native(0x4007A236, [loaded, saved]) & 0xFF
        guarded(loaded, 162)
        return result, bytes(m.uc.mem_read(loaded, 162))

    EXTRAS = 7                         # slots 46-52; slot 0 is the machine's id
    EXTRA_IDS = range(164, 164 + EXTRAS)
    extra_slots = list(range(46, 46 + EXTRAS))
    descriptor = 0x401A9D9C if release.version == '1.53' else 0x401AA09C
    following = descriptor + 164 * 52
    original_descriptors = image[descriptor - dev.main_load:following - dev.main_load]
    original_tables = image[following - dev.main_load:following - dev.main_load + 600]
    native(0x40078B20, [])
    assert bytes(m.uc.mem_read(descriptor, 164 * 52)) == original_descriptors
    assert bytes(m.uc.mem_read(linked.map['mp_legacy_tables'], 600)) == original_tables
    installed = bytes(m.uc.mem_read(following, 52 * EXTRAS))
    native(0x40078B20, [])
    assert bytes(m.uc.mem_read(following, 52 * EXTRAS)) == installed
    # Seven descriptors overwrite 364 of the 600 preserved bytes; the rest stay stock.
    assert bytes(m.uc.mem_read(following + 52 * EXTRAS, 600 - 52 * EXTRAS)) == original_tables[52 * EXTRAS:]
    assert bytes(m.uc.mem_read(linked.map['mp_legacy_tables'], 600)) == original_tables
    for parameter, slot in zip(EXTRA_IDS, extra_slots):
        assert native(0x40078D80, [parameter]) == slot
    for parameter in (171, 172, 0xFFFFFFFF):
        assert native(0x40078D80, [parameter]) == 0xFFFFFFFF
    stock_slot0 = native(0x40078F44, [0, 3])
    for machine in (0, 1, 2, 3, 120, 121, 122, 123, 127):
        for slot in range(53):
            got = native(0x40078F44, [slot, machine])
            if slot >= 46:
                count = EXTRAS if machine in (120, 121) else 0
                assert got == (164 + slot - 46 if slot - 46 < count else 0)
            elif slot == 0:  # the machine's id slot: native for every machine
                assert got == stock_slot0, (machine, got)
            elif 17 <= slot <= 24:
                params = machine if machine <= 3 else 3
                expected = 108 + 8 * params + slot - 17
                assert got == expected, (machine, slot, got, expected)
        for slot in (53, 0xFFFFFFFF):
            assert native(0x40078F44, [slot, machine]) == 0
    protect(sound, 162)
    native(0x40084EF6, [sound, 0, 121])
    guarded(sound, 162)
    assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 29)
    for machine in (120, 121):
        assert native(linked.map['mp_src_for'], [machine]) != 0
    assert native(linked.map['mp_src_for'], [122]) == 0
    for machine in (117, 118, 119, 123, 124, 125, 126, 127):  # 117/118: a trig's or a bank's id as a stock knob
        assert native(linked.map['mp_src_for'], [machine]) == 0
        assert native(linked.map['mp_layout'], [machine]) == 0
    # Only the sound's own stock parameters may be a page's knob: filter, amp, both LFOs.
    stock_ok = [i for i in range(172) if native(linked.map['mp_stock_sound_parameter'], [i])]
    assert stock_ok == list(range(30, 70)), stock_ok

    # These are the native sound reference and parameter objects used by a
    # view; call its encoder scaler/setter, rather than writing sound words.
    parameter, reference = 0x43600100, 0x43600200
    m.ensure(parameter)
    relocation = 0 if release.version == '1.53' else 0x300
    m.uc.mem_write(parameter, struct.pack('>5I', 0x4017EB58 + relocation, 0, 0, 0, reference))
    m.uc.mem_write(reference, struct.pack('>10I', 0x40181330 + relocation, 0, 0, 0, sound, 0, 0, 0, 0, 0))
    native(0x40084EF6, [sound, 0, 121])
    for parameter_id, offset, default in ((164, 112, 13), (170, 124, 7)):
        got = native(0x40010026, [parameter, parameter_id, 256, 0, 0, 0, 0, 0])
        assert got == default + 256, (parameter_id, got)
        assert bytes(m.uc.mem_read(sound + offset, 2)) == struct.pack('>h', default + 256)
        got = native(0x4000FEF6, [parameter, parameter_id, 65535, 0, 0, 0, 0])
        assert got == 0x7F00
        assert bytes(m.uc.mem_read(0x80001502 + offset - 20, 2)) == struct.pack('>h', 0x7F00)
        got = native(0x4000FEF6, [parameter, parameter_id, 0xFFFFFFFF, 0, 0, 0, 0])
        assert got == 0

    # Reset uses metadata defaults; its MIDI UI dispatcher is not booted here.
    def no_midi_ui(uc, address, size, data):
        sp = uc.reg_read(regs.UC_M68K_REG_A7)
        uc.reg_write(pc_register, long_at(sp))
        uc.reg_write(regs.UC_M68K_REG_A7, sp + 4)
    hook = m.uc.hook_add(unicorn.UC_HOOK_CODE, no_midi_ui,
                         begin=0x400104F8, end=0x400104F8)
    try:
        m.uc.mem_write(sound + 112, struct.pack('>2h', 1234, 5678))
        native(0x4000FF9A, [parameter, 164])
        assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 5678)
        native(0x4000FF9A, [parameter, 165])
        assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 29)
        m.uc.mem_write(sound + 112, struct.pack('>2h', 1234, 5678))
        native(0x4000F0AC, [parameter])
        assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 29)
        for machine in (3, 122):
            initialize(machine)
            m.uc.mem_write(sound + 54, bytes(2))
            m.uc.mem_write(sound + 112, struct.pack('>2h', 1234, 5678))
            native(0x4000FF9A, [parameter, 132])
            assert bytes(m.uc.mem_read(sound + 54, 2)) == struct.pack('>h', 0x4000)
            native(0x4000F0AC, [parameter])
            assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 1234, 5678)
        initialize()
    finally:
        m.uc.hook_del(hook)

    # Only the allocator is supplied by the fixture: destination filtering,
    # stepping and the sound write execute the native encoder path unchanged.
    allocator = 0x400D4180 + (0x228 if release.version == '1.54' else 0)
    heap = 0x44100100
    m.ensure(heap)
    def allocate(uc, address, size, data):
        nonlocal heap
        sp = uc.reg_read(regs.UC_M68K_REG_A7)
        if address == allocator:
            amount = long_at(sp + 4)
            assert heap + amount < 0x44200000
            uc.reg_write(regs.UC_M68K_REG_D0, heap)
            heap += (amount + 7) & ~7
        uc.reg_write(regs.UC_M68K_REG_A7, sp + 4)
        uc.reg_write(pc_register, long_at(sp))
    # Native held-step parameter methods route through the track's pattern
    # reference and ID-to-slot lookup, then create/remove a real lock row.
    context, track_data, pattern_data = 0x43700100, 0x43800100, 0x43900100
    for pointer in (context, track_data, pattern_data):
        m.ensure(pointer)
    def ref(pointer, data):
        m.uc.mem_write(pointer, struct.pack('>10I', 0x40181330 + relocation,
                                           0, 0, 0, data, 0, 0, 0, 0, 0))
    root_getter = long_at(0x400107E8)
    put_long(long_at(root_getter + 10), context)
    user_getter = long_at(0x40015788)
    put_long(long_at(user_getter + 10), context + 0x800)
    ref(context + 48, context + 0x900)
    ref(context + 2812 + 112, track_data)
    pattern_ref = context + 0xA00
    ref(pattern_ref, pattern_data)
    put_long(context + 2812 + 112 + 44, pattern_ref)
    put_long(context + 2812 + 112 + 56, 0)
    put_long(long_at(0x4006F40E), pattern_data)
    m.uc.mem_write(track_data + 904, struct.pack('>h', 64))
    m.uc.mem_write(pattern_data, b'\xff' * (6965 * 16))
    put_long(pattern_data + 126052, 0)
    step = 3
    assert native(0x4001589C, [context, 0]) == context + 2812 + 112 + 48
    assert native(0x40024700, [context + 2812 + 112]) == 64
    # Processed identities remain independent across all seven extras and tracks.
    m.uc.mem_write(linked.map['core_track_machine'], bytes([120]) + bytes(6) + bytes([120]))
    processed = linked.map['fw_voice_params']
    m.uc.mem_write(processed - 34, bytes(8 * 106))
    for track in (0, 7):
        values = tuple(1000 + 100 * track + 111 * k for k in range(EXTRAS))
        for slot, value in zip(extra_slots, values):
            m.uc.mem_write(processed + 106 * track + 2 * (slot - 17), struct.pack('>h', value))
        assert tuple(native(linked.map['cm_src_value'], [track, k])
                     for k in range(8, 8 + EXTRAS)) == values
    for track, index in ((8, 8), (0, 15), (0, 16), (0xFFFFFFFF, 0), (1, 8)):
        assert native(linked.map['cm_src_value'], [track, index]) == 0

    # Resolve real SRC-view knob IDs through native press/release handling. The
    # unbooted RTOS sound-lock executor and redraw endpoints are outside this check.
    view, track_ref, track_state, kit_view, event = (
        0x44200100, 0x44200500, 0x44200600, 0x44201000, 0x44202000)
    m.ensure(view)
    ref(track_ref, track_state)
    put_long(view + 116, track_ref)
    put_long(view + 120, kit_view)
    put_long(track_state + 8, 0)
    initialize(120)
    for track in (0, 7):
        ref(kit_view + 96 + 200 * track, sound)
    put_long(linked.map['fw_active_track'], 7)
    m.uc.mem_write(linked.map['fw_slice_layout'] + 8, struct.pack('>8I', *range(132, 140)))
    vtable, native_pages, callbacks = 0x44203000, 0x44204000, 0x44205000
    put_long(view, vtable)
    put_long(view + 124, native_pages)
    put_long(view + 128, native_pages + 8)
    m.uc.mem_write(native_pages, struct.pack('>2I', 4, 5))
    put_long(view + 136, 20)
    for offset, callback in ((80, 0), (180, 4), (184, 8), (188, 12)):
        put_long(vtable + offset, callbacks + callback)
    m.uc.mem_write(callbacks, b'\x4e\x75' * 8)
    gestures = []
    cycle_frame = []
    volatile = [regs.UC_M68K_REG_D1, regs.UC_M68K_REG_A0, regs.UC_M68K_REG_A1,
                regs.UC_M68K_REG_A7]
    armed = 0x40647CA9 if release.version == '1.53' else 0x40648CA9
    redraw = 0x400933DA if release.version == '1.53' else 0x4009341E
    endpoints = (0x4003AA4C, 0x4003A638, redraw)
    def key(code, flags, handler=0x4003B272):
        m.uc.mem_write(event + 12, struct.pack('>2I', code, flags))
        return native(handler, [view, event])
    def click(flags=1):
        key(20, flags)
        assert bytes(m.uc.mem_read(armed, 1)) == b'\x01'
        key(20, 16 | (flags & 4))
        assert long_at(view + 144) == 0
    def view_endpoint(uc, address, size, data):
        if address == 0x4003374E:
            cycle_frame[:] = [uc.reg_read(register) for register in volatile]
            return
        if address == 0x40033754:
            assert [uc.reg_read(register) for register in volatile] == cycle_frame
            assert uc.reg_read(regs.UC_M68K_REG_D0) == long_at(view + 128)
            assert uc.reg_read(regs.UC_M68K_REG_D2) == 1
            return
        if address == 0x40033780:  # Cosmetic page-name popup uses the booted UI heap.
            uc.reg_write(pc_register, 0x400337B0)
            return
        if callbacks <= address <= callbacks + 12:
            gestures.append(address - callbacks)
            return
        sp = uc.reg_read(regs.UC_M68K_REG_A7)
        uc.reg_write(regs.UC_M68K_REG_D0, 0xFFFFFFFF if address == endpoints[0] else 0)
        uc.reg_write(pc_register, long_at(sp))
        uc.reg_write(regs.UC_M68K_REG_A7, sp + 4)
    hooks = [m.uc.hook_add(unicorn.UC_HOOK_CODE, view_endpoint, begin=address, end=address)
             for address in (*endpoints, 0x4003374E, 0x40033754, 0x40033780, callbacks, callbacks + 4,
                             callbacks + 8, callbacks + 12)]
    try:
        assert native(0x4003AAE4, [view, 0]) == 132
        m.uc.mem_write(view + 180, b'\x55' * 200)
        key(20, 1)
        assert bytes(m.uc.mem_read(armed, 1)) == b'\x01'
        assert native(0x4003AAE4, [view, 0]) == 132
        key(20, 16)
        assert long_at(view + 144) == 0
        assert bytes(m.uc.mem_read(view + 20, 1)) == b'\x01'
        assert bytes(m.uc.mem_read(view + 180, 200)) == struct.pack('>5I', 0, 0, 0, 0, 48) * 10
        assert native(0x4003AAE4, [view, 4]) == 168
        assert native(0x4003AAE4, [view, 5]) == 169
        title = native(linked.map['mp_src_title'], [view])
        assert bytes(m.uc.mem_read(title, 10)) == b'PARAM 2/2\0'
        assert native(0x4003AAE4, [view, 7]) == 51  # knob H: the amp's VOL, a stock knob
        put_long(track_state + 8, 7)
        assert native(0x4003AAE4, [view, 4]) == 136
        put_long(track_state + 8, 0)
        put_long(view + 144, 1)  # Enter the extended page from the stock SRC's second native page.
        click(5)
        assert native(0x4003AAE4, [view, 0]) == 132
        for flags in (1, 3, 9, 18):
            m.uc.mem_write(event + 12, struct.pack('>2I', 20, flags))
            assert native(linked.map['mp_src_key'], [view, event]) == 0
        # The real common handler dispatches held SRC+transport actions. The
        # scanner marks the subsequent SRC release as non-click (flags zero).
        physical = long_at(0x4018E7D8 + relocation + 20 * 4)
        held = (0x4217BBF0 if release.version == '1.53' else 0x4217CBF0) + physical // 8
        m.ensure(held)
        m.uc.mem_write(held, bytes([1 << (physical % 8)]))
        click()
        assert native(0x4003AAE4, [view, 4]) == 168
        for transport, callback in ((9, 4), (10, 12), (11, 8)):
            gestures.clear()
            key(20, 1)
            assert native(0x4003AAE4, [view, 4]) == 168
            key(transport, 1)
            assert callback in gestures
            key(20, 0)
            assert native(0x4003AAE4, [view, 4]) == 168
        click()
        m.uc.mem_write(held, b'\0')
        # The same hook preserves native LFO cycling and long-press suppression.
        put_long(view + 136, 23)
        put_long(view + 128, native_pages + 8)
        key(23, 1, 0x40033076)
        assert long_at(view + 144) == 0
        key(23, 16, 0x40033076)
        assert long_at(view + 144) == 1
        put_long(view + 144, 0)
        key(23, 1, 0x40033076)
        key(23, 9, 0x40033076)
        key(23, 16, 0x40033076)
        assert long_at(view + 144) == 0
        put_long(view + 136, 20)
        put_long(view + 128, native_pages + 8)

        # Follow the patched SRC vtable entries, including stock/legacy fallback.
        action_targets = ((0x40032D94, 0x4003A824), (0x40032E42, 0x4003AE06),
                          (0x40032F5C, 0x4003ACC6))
        routed = []
        def route_endpoint(uc, address, size, data):
            sp = uc.reg_read(regs.UC_M68K_REG_A7)
            assert [long_at(sp + 4), long_at(sp + 8)] == [view, 0xFFFFFFFF]
            routed.append(address)
            uc.reg_write(regs.UC_M68K_REG_D0, 0xFACE)
            uc.reg_write(pc_register, long_at(sp))
            uc.reg_write(regs.UC_M68K_REG_A7, sp + 4)
        route_hooks = [m.uc.hook_add(unicorn.UC_HOOK_CODE, route_endpoint, begin=a, end=a)
                       for targets in action_targets for a in targets]
        try:
            for machine in (120, 121, 122, 3):
                initialize(machine)
                for index, targets in enumerate(action_targets):
                    entry = long_at(0x40184988 + relocation + 4 * index)
                    assert native(entry, [view, 0xFFFFFFFF]) == 0xFACE
                    assert routed[-1] == targets[0 if machine in (120, 121) else 1]
        finally:
            for hook in route_hooks:
                m.uc.hook_del(hook)
        initialize(121)
        put_long(view + 144, 1)
        click()
        assert native(0x4003AAE4, [view, 0]) == 164
        assert native(0x4003AAE4, [view, 2]) == 30   # the filter's FREQ
        assert native(0x4003AAE4, [view, 3]) == 0    # blank
        for machine in (122, 3):
            initialize(machine)
            key(20, 1)
            key(20, 16)
            assert long_at(view + 144) == 1
            key(20, 1)
            key(20, 16)
            assert long_at(view + 144) == 0
        initialize(120)
        # Native clipboard collectors retain explicit IDs, even when pasting
        # after changing pages. Only the source object's machine selects values.
        raw_kit, clipboard, id_list, action_stub = 0x44300100, 0x44301000, 0x44301100, 0x44301200
        m.ensure(raw_kit)
        put_long(linked.map['fw_kit'], raw_kit)
        put_long(linked.map['fw_active_track'], 0)
        m.uc.mem_write(raw_kit + 32, bytes(m.uc.mem_read(sound, 162)))
        for page in (4, 5):
            layout = native(0x400657B2, [page])
            m.uc.mem_write(layout + 8, struct.pack('>8I', *range(108, 116)))
        native_layout = native(0x400657B2, [2])
        m.uc.mem_write(native_layout + 8, struct.pack('>8I', *range(52, 60)))
        m.uc.mem_write(action_stub, bytes.fromhex('206f00042f2f000c2f2f000c4eb940011ab8508f4e75'))
        m.uc.mem_write(action_stub + 32, bytes.fromhex('206f00042f2f00084eb94001128c588f4e75'))
        action_hooks = [m.uc.hook_add(unicorn.UC_HOOK_CODE, allocate, begin=a, end=a)
                        for a in (allocator, allocator + 12)]
        action_hooks.append(m.uc.hook_add(unicorn.UC_HOOK_CODE, no_midi_ui,
                                         begin=0x400104F8, end=0x400104F8))
        def collected(pointer, stride):
            first, last = struct.unpack('>2I', m.uc.mem_read(pointer, 8))
            return [long_at(p) for p in range(first, last, stride)]
        try:
            for logical in range(8 + EXTRAS):
                slot = 17 + logical if logical < 8 else 46 + logical - 8
                m.uc.mem_write(sound + 20 + 2 * slot, struct.pack('>h', 1000 + logical))
            machine_id = struct.pack('>H', 0x5A5B)  # slot 0: a hashed machine id, never an SRC value
            m.uc.mem_write(sound + 20, machine_id)
            vol = sound + 20 + 2 * 45                # page 2's knob H, the amp's VOL (slot 45)
            m.uc.mem_write(vol, struct.pack('>h', 0x1234))
            native(action_stub, [clipboard, parameter, 4])
            assert collected(clipboard, 8) == list(range(132, 140))
            click()
            native(action_stub, [clipboard, parameter, 5])
            page_ids = list(EXTRA_IDS) + [51]  # the eighth knob is the amp's VOL
            def page_two(ids):
                return ids == page_ids
            got = collected(clipboard, 8)
            assert page_two(got), got
            native(action_stub + 32, [id_list, 4])
            got = collected(id_list, 4)
            assert page_two(got), got
            # Extras borrow the native randomizer from look 134.
            record = native(0x40065794, [134])
            m.uc.mem_write(record + 52, struct.pack('>4I', action_stub + 64, 0, 0x40062914, 0x400632D4))
            native(0x4000F154, [parameter, id_list])
            assert bytes(m.uc.mem_read(sound + 112, 4)) != struct.pack('>2h', 1008, 1009)
            assert bytes(m.uc.mem_read(sound + 54, 2)) == struct.pack('>h', 1000)
            native(0x4000F0E4, [parameter, id_list])
            assert bytes(m.uc.mem_read(sound + 112, 14)) == bytes(14)
            assert bytes(m.uc.mem_read(sound + 20, 2)) == machine_id
            got = bytes(m.uc.mem_read(vol, 2))  # the page's clear resets the stock knob to its default
            assert got == struct.pack('>h', 0x6E00), got.hex()
            click()
            native(0x40011BD8, [parameter, clipboard, 0, 0])
            assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 1008, 1009)
            assert bytes(m.uc.mem_read(sound + 54, 2)) == struct.pack('>h', 1000)
            assert bytes(m.uc.mem_read(sound + 112, 14)) == struct.pack('>7h', *range(1008, 1015))
            assert bytes(m.uc.mem_read(sound + 20, 2)) == machine_id
            assert bytes(m.uc.mem_read(vol, 2)) == struct.pack('>h', 0x1234)  # and paste brings it back
            for parameter_id in (132, 164, 165, 51):
                assert native(0x400107D2, [parameter, parameter_id, 2000, step]) & 0xFF == 1
            assert native(0x4001076E, [parameter, 51, step]) == 2000  # a lock on the stock knob
            for parameter_id in collected(id_list, 4):
                if parameter_id:
                    native(0x4001083E, [parameter, parameter_id, step])
            assert native(0x4001076E, [parameter, 132, step]) == 2000
            assert native(0x4001076E, [parameter, 164, step]) == 0xFFFFFFFF
            assert native(0x4001076E, [parameter, 165, step]) == 0xFFFFFFFF
            assert native(0x4001076E, [parameter, 51, step]) == 0xFFFFFFFF
            initialize(122)
            native(action_stub, [clipboard, parameter, 4])
            assert collected(clipboard, 8) == list(range(108, 116))
            for machine, track, page, expected in ((122, 0, 4, list(range(108, 116))),
                                                   (120, 8, 4, list(range(108, 116))),
                                                   (120, 0, 2, list(range(52, 60)))):
                m.uc.mem_write(raw_kit + 32 + 126, bytes([machine]))
                put_long(linked.map['fw_active_track'], track)
                native(action_stub + 32, [id_list, page])
                assert collected(id_list, 4) == expected
            initialize(121)
            m.uc.mem_write(raw_kit + 32 + 126, b'\x79')
            native(action_stub + 32, [id_list, 4])
            native(0x4000F0E4, [parameter, id_list])
            assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 29)
        finally:
            for action_hook in action_hooks:
                m.uc.hook_del(action_hook)
    finally:
        for hook in hooks:
            m.uc.hook_del(hook)

    # An existing UI3 machine keeps native reset/pop-up behavior and its LFO name.
    initialize(122)
    assert native(linked.map['mp_layout'], [122]) != 0
    m.uc.mem_write(raw_kit + 32, bytes(m.uc.mem_read(sound, 162)))
    put_long(linked.map['fw_active_track'], 0)
    name = native(linked.map['mp_lfo'], [132, 1, 0])
    assert bytes(m.uc.mem_read(name, 8)) == b'Old LFO\0'
    forwarded_ids = []
    def native_popup(uc, address, size, data):
        forwarded_ids.append(uc.reg_read(regs.UC_M68K_REG_D1))
        no_midi_ui(uc, address, size, data)
    hook = m.uc.hook_add(unicorn.UC_HOOK_CODE, native_popup,
                         begin=0x400657F8, end=0x400657F8)
    try:
        native(0x400657EE, [132, 0x4000])
        assert forwarded_ids == [132]  # Borrowing look134 must not change the native pop-up.
    finally:
        m.uc.hook_del(hook)

    # One fifteen-value lifecycle: native edits/locks, real destination choices,
    # processed LFO output, then lossless serialized sound.
    def extras_at(pointer):
        return tuple(struct.unpack('>h', m.uc.mem_read(pointer + 20 + 2 * slot, 2))[0]
                     for slot in extra_slots)
    probe_defaults = (13, 29, 3, 4, 5, 6, 7)

    native(0x40084EF6, [sound, 0, 121])
    assert extras_at(sound) == probe_defaults
    m.uc.mem_write(sound + 22, b'\xff\xff')
    m.uc.mem_write(sound + 20, b'\xff\xff')  # slot 0 is raw: whatever id it holds comes back
    normalized_source = bytes(m.uc.mem_read(sound, 162))
    assert native(0x4007A5A0, [saved, sound, 0]) & 255 == 1
    assert bytes(m.uc.mem_read(sound, 162)) == normalized_source
    assert load(bytes(m.uc.mem_read(saved, 160)))[0] == 1
    assert bytes(m.uc.mem_read(loaded + 22, 2)) == bytes(2)
    assert bytes(m.uc.mem_read(loaded + 20, 2)) == b'\xff\xff'
    assert extras_at(loaded) == probe_defaults
    native(0x40084EF6, [sound, 0, 120])
    assert extras_at(sound) == (0,) * EXTRAS
    original_src = bytes(m.uc.mem_read(sound + 54, 16))
    for k, slot in enumerate(extra_slots):
        value = 777 * (k + 1)
        assert native(0x4000FEF6, [parameter, 164 + k, value, 0, 0, 0, 0]) == value
        assert native(0x400107D2, [parameter, 164 + k, value + 256, step]) & 255 == 1
        assert native(0x4001076E, [parameter, 164 + k, step]) == value + 256
        assert native(0x4000F18C, [parameter, 164 + k, 256, step]) == value + 512
        assert native(0x4001083E, [parameter, 164 + k, step]) & 255 == 1
    assert extras_at(sound) == tuple(777 * (k + 1) for k in range(EXTRAS))
    assert bytes(m.uc.mem_read(sound + 54, 16)) == original_src
    note_lock = bytes(m.uc.mem_read(pattern_data + step * 108, 2))
    native(0x40024942, [context + 2812 + 112, step, 60])
    assert native(0x40024374, [context + 2812 + 112, step]) & 255 == 60
    assert bytes(m.uc.mem_read(pattern_data + step * 108, 2)) == note_lock
    hooks = [m.uc.hook_add(unicorn.UC_HOOK_CODE, allocate, begin=a, end=a)
             for a in (allocator, allocator + 12)]
    try:
        # The stock chooser itself reaches the extras' slots: no extra destination is added.
        for parameter_id, offset in ((55, 28), (64, 44)):
            m.uc.mem_write(sound + offset, struct.pack('>h', 51 << 8))
            got = native(0x40010026, [parameter, parameter_id, 256, 0, 0, 0, 0, 0])
            assert got == 52 << 8, (parameter_id, hex(got))
            got = native(0x40010026, [parameter, parameter_id, 256, 0, 0, 0, 0, 0])
            assert got == 52 << 8, (parameter_id, hex(got))  # the last destination
            got = native(0x40010026, [parameter, parameter_id, 0xFFFFFF00, 0, 0, 0, 0, 0])
            assert got == 51 << 8, (parameter_id, hex(got))
            last = extras_at(sound)[-1]
            assert native(0x4000FEF6, [parameter, parameter_id, 0, 0, 0, 0, 0]) == 0
            assert extras_at(sound)[-1] == last
        assert native(0x4000F3B4, [parameter, 0]) == 17
        for slot, parameter_id in zip(extra_slots, EXTRA_IDS):
            assert native(0x4000F3B4, [parameter, slot]) == parameter_id
    finally:
        for hook in hooks:
            m.uc.hook_del(hook)

    lfo_state = 0x421F3E10 + (0x1000 if release.version == '1.54' else 0)
    m.ensure(lfo_state)
    for destinations in ((46, 52), (0, 0)):
        native(0x40084EF6, [sound, 0, 120])
        values = list(struct.unpack('>53h', m.uc.mem_read(sound + 20, 106)))
        for slot in extra_slots:
            values[slot] = 8000
        values[0] = 0x5A5B  # a machine id; an LFO with no destination must not reach the extras
        values[4], values[12] = (d << 8 for d in destinations)
        values[1] = values[9] = 0x5000
        values[5] = values[13] = 2 << 8
        values[6] = values[14] = 0x4000
        values[7] = values[15] = 1 << 8
        values[8] = values[16] = 0x4800
        m.uc.mem_write(sound + 20, struct.pack('>53h', *values))
        m.uc.mem_write(lfo_state, bytes(640))
        native(0x40077282, [sound, 0])
        put_long(0x800019B4, 0)  # Native edits can clear a noncanonical sound pointer.
        m.uc.emu_start(0x40074732, 0x40074738, count=1)
        output = native(0x40074B9E, [0x800014F0])
        m.uc.emu_start(0x4006A868, 0x4006A86E, count=1)
        native(0x400ED53E + (0x228 if release.version == '1.54' else 0), [output, 14400, 255])
        got = extras_at(output - 2)
        assert got == ((12095,) + (8000,) * 5 + (12095,) if destinations[0] else (8000,) * EXTRAS), got
        assert extras_at(sound) == (8000,) * EXTRAS
        assert bytes(m.uc.mem_read(sound + 20, 2)) == b'\x5a\x5b'  # the id is read from the sound
        assert native(linked.map['cm_src_value'], [0, 8 + EXTRAS - 1]) == got[-1]

    native(0x40084EF6, [sound, 0, 120])
    m.uc.mem_write(sound + 4, b'FIFTEEN VALUES\0\0')
    words = [slot * 173 for slot in range(1, 46)]
    words[16] = 0xFF85  # Original SRC words retain custom signed representations.
    words[19] = 0      # The fixture has no sample reference.
    words[3], words[11] = 52 << 8, 46 << 8
    m.uc.mem_write(sound + 22, struct.pack('>45H', *words))
    extra_values = (0, 1, 255, 256, 0x1234, 0x4500, 0x7F00)
    for slot, value in zip(extra_slots, extra_values):
        m.uc.mem_write(sound + 20 + 2 * slot, struct.pack('>h', value))
    m.uc.mem_write(sound + 20, b'\xa5\xc3')  # slot 0: a machine id, its last bit set
    source_before = bytes(m.uc.mem_read(sound, 162))
    protect(saved, 160)
    assert native(0x4007A5A0, [saved, sound, 0]) & 255 == 1
    guarded(saved, 160)
    packed16 = bytes(m.uc.mem_read(saved, 160))
    assert struct.unpack_from('>I', packed16, 4)[0] == 4
    assert packed16[131] & 0x1F == 0x10  # bit 803, the id's last, ends the stream
    assert bytes(m.uc.mem_read(sound, 162)) == source_before
    ok, restored16 = load(packed16)
    assert ok == 1 and extras_at(loaded) == extra_values
    assert restored16[20:22] == b'\xa5\xc3'
    assert list(struct.unpack_from('>45H', restored16, 22)) == words
    assert restored16[4:20] == b'FIFTEEN VALUES\0\0'
    assert restored16[129:134] == b'\xcc' * 5
    hooks = [m.uc.hook_add(unicorn.UC_HOOK_CODE, allocate, begin=a, end=a)
             for a in (allocator, allocator + 12)]
    try:
        for changed_pointer in (0, event):
            m.uc.mem_write(event, b'\xff')
            assert native(0x4007F708, [saved, changed_pointer, 3]) & 255 == 1
            assert bytes(m.uc.mem_read(saved, 160)) == packed16
            if changed_pointer:
                assert bytes(m.uc.mem_read(event, 1)) == bytes(1)
        assert native(0x4007F930, [loaded, saved, 0]) & 255 == 1
        assert extras_at(loaded) == extra_values
        assert bytes(m.uc.mem_read(loaded + 20, 2)) == b'\xa5\xc3'
    finally:
        for hook in hooks:
            m.uc.hook_del(hook)
    malformed = bytearray(packed16)
    malformed[131] |= 1
    assert load(malformed) == (0, b'\xcc' * 162)
    # Main's ordinary records keep native conversion; extension padding is ignored.
    initialize(122)
    assert native(0x4007A5A0, [saved, sound, 0]) & 255 == 1
    baseline = bytes(m.uc.mem_read(saved, 160))
    assert struct.unpack_from('>I', baseline, 4)[0] == 3
    unchanged = load(baseline)
    changed = bytearray(baseline)
    changed[120:124] = b'\xff' * 4
    assert load(changed) == unchanged
    changed[124] = 121
    assert load(changed)[0] == 1
    assert extras_at(loaded) == probe_defaults
    assert native(0x4007A5A0, [saved, 0, 0]) & 255 == 0
    assert native(0x4007A236, [loaded, 0]) & 255 == 0
    invalid = bytearray(baseline)
    struct.pack_into('>I', invalid, 4, 99)
    assert load(invalid) == (0, b'\xcc' * 162)

    # Exercise the real eight-track kit and 128-entry pool converters.
    for save_fn, load_fn, count, source_head, saved_head, source_len, saved_len in (
        (0x4007A6A6, 0x4007A4CE, 8, 32, 36, 2334, 2292),
        (0x4007A786, 0x4007A4EA, 128, 0, 4, 130 * 162, 4 + 130 * 160),
    ):
        source, packed, restored = 0x43300100, 0x43400100, 0x43500100
        for pointer in (source, packed, restored):
            m.ensure(pointer)
        m.uc.mem_write(source, bytes(source_len))
        m.uc.mem_write(packed, bytes(saved_len))
        machines = [120 if i in (0, count - 1) else 121 if i == count // 2 else 122 if i == 1 else 3
                    for i in range(count)]
        for i, machine in enumerate(machines):
            initialize(machine)
            m.uc.mem_write(sound + 112, struct.pack('>2h', i, i * 123))
            m.uc.mem_write(sound + 20, struct.pack('>H', 0x8000 + 0x101 * i))  # every sound's id
            if machine in (120, 121):
                for k, slot in enumerate(extra_slots):
                    m.uc.mem_write(sound + 20 + 2 * slot, struct.pack('>h', i + 777 * k))
                m.uc.mem_write(sound + 28, struct.pack('>h', 52 << 8))
                m.uc.mem_write(sound + 44, struct.pack('>h', 47 << 8))
            m.uc.mem_write(source + source_head + 162 * i, bytes(m.uc.mem_read(sound, 162)))
        protect(packed, saved_len)
        protect(restored, source_len)
        assert native(save_fn, [packed, source, 0]) & 0xFF == 1
        guarded(packed, saved_len)
        assert native(load_fn, [restored, packed]) & 0xFF == 1
        guarded(restored, source_len)
        for i, machine in enumerate(machines):
            got = bytes(m.uc.mem_read(restored + source_head + 162 * i, 162))
            assert got[126] == machine
            assert struct.unpack_from('>H', got, 20)[0] == (0x8000 + 0x101 * i) & 0xFFFF, (machine, i)
            if machine in (120, 121):
                assert tuple(struct.unpack_from('>h', got, 20 + 2 * slot)[0] for slot in extra_slots) == tuple(i + 777 * k for k in range(EXTRAS))
                assert struct.unpack_from('>h', got, 28)[0] == 52 << 8
                assert struct.unpack_from('>h', got, 44)[0] == 47 << 8
            else:
                assert got[112:126] == bytes(14)

    for machine in (0, 3, 119, 120, 121, 122, 123, 127):
        for parameter_id in (163, 164, 165, 166, 170, 171):
            got = native(linked.map['mp_randomize_owner_s'],
                         [parameter_id, 0, 0, 0, 0, 0, 0, machine])
            extended = machine in (120, 121)
            expected = ((3 if extended else 0xFFFFFFFF) if parameter_id in EXTRA_IDS
                        else native(0x40079034, [parameter_id]))
            assert got == expected, (machine, parameter_id, got)

    # Exercise the machine setter's reset call with a sound reference whose
    # event callback is inert; no project/event bus is booted in this probe.
    fake_vtable, no_event = 0x43600500, 0x43600600
    vtable = bytearray(m.uc.mem_read(0x40181330 + relocation, 44))
    struct.pack_into('>I', vtable, 16, no_event)
    m.uc.mem_write(fake_vtable, bytes(vtable))
    m.uc.mem_write(no_event, b'\x4e\x75')
    reset_call = no_event + 4
    # The caller owns argument cleanup at this patched call site.
    m.uc.mem_write(reset_call, bytes.fromhex('2f2f0010') * 4 +
                   bytes(m.uc.mem_read(0x4002264E, 8)) + b'\x4e\x75')
    m.uc.mem_write(reference, struct.pack('>I', fake_vtable))
    initialize()
    m.uc.mem_write(sound + 112, bytes(4))
    updates = []
    def sound_update(uc, address, size, data):
        sp = uc.reg_read(regs.UC_M68K_REG_A7)
        updates.append((long_at(sp + 4), long_at(sp + 8),
                        bytes(uc.mem_read(sound + 112, 4))))
    hook = m.uc.hook_add(unicorn.UC_HOOK_CODE, sound_update, begin=no_event, end=no_event)
    try:
        assert native(reset_call, [reference, 1, 3, 0]) & 0xFF == 1
    finally:
        m.uc.hook_del(hook)
    assert bytes(m.uc.mem_read(sound + 112, 4)) == struct.pack('>2h', 13, 29)
    assert updates[-1] == (reference, 0, struct.pack('>2h', 13, 29))
    m.uc.mem_write(reference, struct.pack('>I', 0x40181330 + relocation))

    # Pattern lock records hold 79 usable parameter/track lanes. Preserve
    # ordinary/MIDI permutations and round-trip the seven added audio lanes (and slot 0's).
    lock_runtime, lock_saved, lock_loaded = 0x43700100, 0x43800100, 0x43900100
    for pointer, length in ((lock_runtime, 111440), (lock_saved, 10400), (lock_loaded, 111440)):
        m.load(bytes(length), pointer)
        protect(pointer, length)
    m.uc.mem_write(lock_saved, b'\xff' * 10400)
    assert native(0x4007ABB2, [lock_runtime, lock_saved], limit=2_000_000) & 0xFF == 1
    lanes = ([(0, slot) for slot in range(53)] + [(7, slot) for slot in [*range(46, 53), 0]] +
             [(8, slot) for slot in range(9)] + [(15, slot) for slot in range(37, 46)])
    assert len(lanes) == 79
    for track, slot in lanes:
        for step in (0, 63):
            value = 1000 + 100 * track + 10 * slot + step
            m.uc.mem_write(lock_runtime + 6965 * track + 108 * step + 2 * slot,
                           struct.pack('>h', value))
        m.uc.mem_write(lock_runtime + 6965 * track + 6912 + slot, b'\x01')
    assert native(0x4007ADB2, [lock_saved, lock_runtime], limit=2_000_000) & 0xFF == 1
    packed_locks = bytes(m.uc.mem_read(lock_saved, 10400))
    assert sum(packed_locks[i] != 255 for i in range(0, 10400, 130)) == 79
    assert native(0x4007ABB2, [lock_loaded, lock_saved], limit=2_000_000) & 0xFF == 1
    for track, slot in lanes:
        for step in (0, 1, 63):
            value = 1000 + 100 * track + 10 * slot + step if step != 1 else -1
            got = bytes(m.uc.mem_read(lock_loaded + 6965 * track + 108 * step + 2 * slot, 2))
            assert got == struct.pack('>h', value), (track, slot, step, got)
    for pointer, length in ((lock_runtime, 111440), (lock_saved, 10400), (lock_loaded, 111440)):
        guarded(pointer, length)
    save_map = 0x401AC1D4 + relocation
    inverse = struct.unpack('>46I', m.uc.mem_read(save_map + 46 * 4, 46 * 4))
    for track in (0, 7, 8, 15):
        for slot in range(46):
            assert native(0x40079738, [track, slot]) == inverse[slot]
        for slot in range(46, 53):
            assert native(0x40079738, [track, slot]) == (slot if track < 8 else 0)

    return {
        'mode': 'shared implementation; runtime loaded directly, no boot',
        'fifteen_value_native_lifecycle_and_standalone_codec': True,
        'slot_0_machine_id_survives_codec_actions_kits_pools_and_lfo_none': True,
        'stock_and_legacy_records_ignore_extension': True,
        'legacy_ui3_reset_popup_and_lfo_names_match_main': True,
        'invalid_extended_descriptors_rejected_by_companion': True,
        'mixed_kits_and_pools_preserve_values_and_lfo_assignments': True,
        'native_failures_registers_stack_and_buffer_guards_preserved': True,
        'extra_descriptor_ids_slots_and_constructor_defaults': True,
        'original_descriptors_and_relocated_tables_preserved': True,
        'native_slot_and_descriptor_bounds_preserved': True,
        'native_encoder_edits_and_clamps_both_extra_base_values': True,
        'individual_and_all_parameter_resets_use_metadata_defaults': True,
        'native_held_step_edit_and_removal_leave_base_values_unchanged': True,
        'stock_lfo_destination_chooser_reaches_slots_46_52_and_none': True,
        'a_page_knob_may_be_a_stock_sound_parameter_that_edits_locks_clears_and_pastes': True,
        'only_filter_amp_and_lfo_parameters_may_be_stock_knobs': True,
        'processed_accessor_keeps_seven_extra_identities_and_tracks': True,
        'native_src_view_knobs_follow_per_track_page_selection': True,
        'native_src_release_cycles_while_held_copy_clear_paste_keep_the_page': True,
        'native_lfo_cycle_and_long_press_behavior_preserved': True,
        'src_page_release_marks_view_dirty_and_resets_all_native_knob_caches': True,
        'native_src_copy_clear_randomize_use_visible_controls_and_keep_clipboard_ids': True,
        'src_actions_preserve_other_pages_legacy_midi_and_blank_slots': True,
        'actual_src_vtable_routes_extended_actions_and_preserves_stock_legacy_handlers': True,
        'bounded_ui_endpoints_supplied_by_fixture': ['allocator', 'sound-lock RTOS executor',
                                                    'redraw/page-name popup', 'page-action callbacks/route endpoints', 'MIDI UI dispatch'],
        '79_persisted_lock_lanes_include_seven_extras_on_first_and_last_audio_tracks': True,
        'ordinary_and_midi_lock_permutations_preserved': True,
        'native_machine_reset_uses_metadata_defaults': True,
        'randomize_reload_extra_ownership_is_machine_specific': True,
    }
