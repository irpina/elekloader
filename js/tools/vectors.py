# SPDX-License-Identifier: GPL-2.0-or-later
"""Writes js/test/vectors.json: what elekloader's Python gives for synthetic inputs (no firmware), so the
TypeScript engine's tests can check it says the same without any stock file. Run from the repository root:

    python js/tools/vectors.py
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from elekloader import elek                                   # noqa: E402
from elekloader.codec import aplib, elz, transport            # noqa: E402


def lcg(seed, n):
    """The inputs' generator; test/codec.test.ts has the same one."""
    out = bytearray(n)
    s = seed & 0xFFFFFFFF
    for i in range(n):
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        out[i] = s >> 24
    return bytes(out)


def make(spec):
    kind, n = spec['kind'], spec['n']
    if kind == 'random':
        return lcg(spec['seed'], n)
    if kind == 'repeat':
        return bytes([spec['value']]) * n
    if kind == 'phrase':
        p = spec['text'].encode()
        return (p * (n // len(p) + 1))[:n]
    if kind == 'blocks':      # random blocks, some repeated near and far: matches of every kind
        r = lcg(spec['seed'], n)
        out = bytearray(r)
        for k, at in enumerate(range(512, n - 300, 997)):
            src = at - (37 + (k * 811) % 6000)
            if src >= 0:
                ln = 3 + (k * 13) % 260
                out[at:at + ln] = out[src:src + ln]
        return bytes(out[:n])
    if kind == 'words':       # big-endian counters with zeros: like code and tables
        out = bytearray()
        for i in range(n // 4):
            out += (i * 6 if i % 5 else 0).to_bytes(4, 'big')
        return bytes(out)
    raise ValueError(kind)


SPECS = [
    {'kind': 'random', 'seed': 0, 'n': 0},
    {'kind': 'random', 'seed': 1, 'n': 1},
    {'kind': 'random', 'seed': 2, 'n': 2},
    {'kind': 'random', 'seed': 3, 'n': 3},
    {'kind': 'random', 'seed': 4, 'n': 4},
    {'kind': 'repeat', 'value': 0, 'n': 5000},
    {'kind': 'repeat', 'value': 0x2A, 'n': 20},
    {'kind': 'phrase', 'text': 'ab', 'n': 8000},
    {'kind': 'phrase', 'text': 'tape delay ', 'n': 3000},
    {'kind': 'random', 'seed': 7, 'n': 500},
    {'kind': 'random', 'seed': 8, 'n': 70000},
    {'kind': 'blocks', 'seed': 9, 'n': 40000},
    {'kind': 'blocks', 'seed': 10, 'n': 300000},
    {'kind': 'words', 'n': 200000},
]


def sha(b):
    return hashlib.sha256(b).hexdigest()


JSON_TEXTS = [
    '{"a": 1}', '{"a": 1.0, "b": -2.5e3, "c": NaN, "d": Infinity, "e": -Infinity}', '[1, 2,]', '{"a": 1,}',
    '{"a" 1}', '{"a": }', '{a: 1}', '', '   ', 'x', '{"a": 1} x', '{"a": "b\\qc"}', '{"a": "b\x01c"}',
    '{"a": "abc', '{"a": "\\u00e9\\ud83d\\ude00"}', '{"a": "\\u12"}', '[1 2]', '{"a": 1 "b": 2}', '01',
    '-', '{"a": [}', '\n\n  {"a":\n  x}', '{"a": tru}', '"\\/"', '{"a":1}\n', '[\n1,\n2\n,]', '﻿{}',
]
UTF8 = ['efbbbf7b7d', '7bff7d', 'c0', 'e282', 'e2', 'e282417d', 'eda080', 'f4908080', 'f0808080', '22e2828c22', '7b22ce', 'f0']
INTS = ['16', '0x10', '0X1f', '0o17', '0b101', '010', '0', '00', '-5', '+7', ' 12 ', '1_000', '0x_ff', '1__0', '_1',
        '', 'abc', '1.5', '0x', '٣']
REPRS = [[1, 'a', None, True], {'k': [1, 2], 'q': "it's"}, 'a"b', "a'b", 'a\nb\\', 'é', ['x', ['y']]]
FLOATS = [0.0, -0.0, 1.0, 4.0, 1.5, 0.1, 1e16, 1e15, 123456789012345.6, 1e-5, 0.0001, 2.5e-7, 1e100, -3.0,
          1 / 3, 5e-324, 1.7976931348623157e308]


def python_vectors():
    import io
    import zipfile
    jt = []
    for t in JSON_TEXTS:
        try:
            v = json.loads(t)
            jt.append({'text': t, 'value': json.dumps(v, allow_nan=True, sort_keys=False),
                       'floats': repr_floats(v)})
        except json.JSONDecodeError as e:
            jt.append({'text': t, 'error': str(e)})
    u8 = []
    for h in UTF8:
        try:
            u8.append({'hex': h, 'text': bytes.fromhex(h).decode('utf-8')})
        except UnicodeDecodeError as e:
            u8.append({'hex': h, 'error': str(e)})
    ints = []
    for s in INTS:
        try:
            ints.append({'s': s, 'value': int(s, 0)})
        except ValueError:
            ints.append({'s': s, 'value': None})
    dumps_in = {'b': 1, 'a': [1, 'xé\x01"', None, True, 2.5, {}], 'z': {}, '3': {'k': []}, 'e': []}
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w') as z:
        z.writestr('dir/', b'')
        z.writestr(zipfile.ZipInfo('stored.bin'), lcg(21, 300))
        z.writestr('deflated.syx', lcg(22, 5000) + bytes(4000), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr('néme.txt'.encode('utf-8').decode('cp437'), b'hello')
    zraw = zbuf.getvalue()
    zm = []
    with zipfile.ZipFile(io.BytesIO(zraw)) as z:
        for i in z.infolist():
            zm.append({'filename': i.filename, 'size': i.file_size, 'dir': i.is_dir(),
                       'sha256': sha(z.read(i)) if not i.is_dir() else None})
    return {
        'json': jt, 'utf8': u8, 'int': ints,
        'repr': [{'value': v, 'repr': repr(v)} for v in REPRS],
        'float_repr': [{'value': f, 'repr': repr(f)} for f in FLOATS],
        'dumps': {'value': dumps_in, 'indent1': json.dumps(dumps_in, indent=1),
                  'indent0': json.dumps(dumps_in, indent=0), 'flat': json.dumps(dumps_in)},
        'zip': {'hex': zraw.hex(), 'members': zm},
        'cp437': bytes(range(128, 256)).decode('cp437'),
    }


def repr_floats(v):
    """Where json.loads gave floats, by path: the JS side reads those as PyFloat."""
    out = []

    def walk(x, path):
        if isinstance(x, float):
            out.append([path, repr(x)])
        elif isinstance(x, dict):
            for k, y in x.items():
                walk(y, path + '/' + k)
        elif isinstance(x, list):
            for i, y in enumerate(x):
                walk(y, path + '/' + str(i))
    walk(v, '')
    return out


def main():
    cases = []
    for spec in SPECS:
        data = make(spec)
        packed = aplib.pack_section(data)
        store = aplib.pack_section(data, compress=False)
        assert elz.depack_section(packed) == data
        c = {'spec': spec, 'input_sha256': sha(data), 'packed_sha256': sha(packed),
             'packed_len': len(packed), 'store_sha256': sha(store)}
        if len(packed) <= 256:
            c['packed'] = packed.hex()
        cases.append(c)
    # the transport: a made-up stream between made-up framing messages (device 0x0A, constant 0x0F)
    stream = lcg(11, 5 * 101 + 37)
    fs = bytes([0xF0, 0, 0x20, 0x3C, 0x0A, 0, 0x7D, 0, 0x0F, 1, 2, 3, 0, 0, 0, 0xF7])
    fe = bytes([0xF0, 0, 0x20, 0x3C, 0x0A, 0, 0x7F, 0, 0x0F, 4, 5, 6, 0, 0, 0, 0xF7])
    syx = transport.encode_syx(stream, 0x0A, fs, fe)
    container = lcg(12, 4099)
    # the Octatrack's: its legacy SysEx and its card file, for a made-up container
    oc = b'ELEK0178' + b'     1.40C' + lcg(13, 1000)
    out = {
        'note': 'Written by js/tools/vectors.py from elekloader\'s Python; synthetic inputs, no firmware.',
        'aplib': cases,
        'transport': {'stream_seed': 11, 'stream_len': len(stream), 'framing': [fs.hex(), fe.hex()],
                      'syx_sha256': sha(syx), 'syx_len': len(syx),
                      'content_checksum': {'seed': 12, 'len': len(container),
                                           'value': transport.content_checksum(container)}},
        'elek': {'container_seed': 13, 'syx_sha256': sha(elek.encode_syx(oc, 0x05)),
                 'bin_sha256': sha(elek.encode_bin(oc, 0x2F1349D2)),
                 'bin_odd_sha256': sha(elek.encode_bin(oc + b'\x01', 0x00800001))},
    }
    out['python'] = python_vectors()
    path = os.path.join(ROOT, 'js', 'test', 'vectors.json')
    with open(path, 'w') as fh:
        json.dump(out, fh, indent=1)
        fh.write('\n')
    print('wrote', path, len(cases), 'aplib cases')


if __name__ == '__main__':
    main()
