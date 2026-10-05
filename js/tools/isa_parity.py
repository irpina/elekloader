# SPDX-License-Identifier: GPL-2.0-or-later
"""The Python half of tools/isa_parity.ts: decodes the instruction at every even offset of a stock file's main OS
with elekloader's decoder and writes, per offset, its length, flags, flow, op and target (8 bytes, big-endian).

    python3 js/tools/isa_parity.py <stock file> <out.bin>

The output describes the firmware's instructions; like the firmware, it stays on your machine.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from elekloader import formats                   # noqa: E402
from elekloader.isa import coldfire as cf        # noqa: E402

FLOWS = ['none', 'bcc', 'bra', 'bsr', 'jmp', 'jsr', 'rts', 'rte', 'trap']


def main():
    stock, out = sys.argv[1:3]
    s, dev, rel = formats.load(stock)
    img = formats.main_image(s, dev)
    read = cf.reader(img, dev.main_load)
    ops, rec = {}, bytearray()
    for off in range(0, len(img) - 1, 2):
        a = dev.main_load + off
        try:
            ins = cf.decode(read(a), a)
            op = ops.setdefault(ins.op, len(ops))
            t = 0xFFFFFFFF if ins.target is None else ins.target
            rec += struct.pack('>BBBBI', ins.length, ins.flags, ins.flow, op, t)
        except IndexError:
            rec += struct.pack('>BBBBI', 0, 0, 0, 255, 0)     # a read past the image's end
    with open(out, 'wb') as fh:
        fh.write(rec)
    with open(out + '.json', 'w') as fh:
        json.dump({'ops': sorted(ops, key=ops.get), 'flows': FLOWS, 'device': dev.key, 'os': rel.version,
                   'main_load': dev.main_load, 'n': len(rec) // 8}, fh)
    print('%s %s: %d offsets, %d ops' % (dev.name, rel.version, len(rec) // 8, len(ops)))


if __name__ == '__main__':
    main()
