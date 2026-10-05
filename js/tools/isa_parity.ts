// SPDX-License-Identifier: GPL-3.0-or-later
// The decoder against elekloader's Python, at every even offset of a stock file's main OS: tools/isa_parity.py
// writes what the Python decodes there; this decodes the same and says where (if anywhere) they differ.
//
//   python3 tools/isa_parity.py <stock file> <out.bin>
//   node tools/isa_parity.ts <stock file> <out.bin>
import { readFileSync } from 'node:fs'
import { load, mainImage } from '../src/formats.ts'
import { decodeColdFire, readerAt } from '../src/isa/coldfire.ts'

const [, , stockPath, recPath] = process.argv
const meta = JSON.parse(readFileSync(recPath + '.json', 'utf8'))
const rec = new Uint8Array(readFileSync(recPath))
const [s, dev] = await load(new Uint8Array(readFileSync(stockPath)))
const img = mainImage(s, dev)
const read = readerAt(img, dev.mainLoad)
const view = new DataView(rec.buffer, rec.byteOffset, rec.byteLength)
let diffs = 0
const t0 = performance.now()
for (let i = 0; i < meta.n; i++) {
  const a = dev.mainLoad + 2 * i
  const want = { length: rec[8 * i], flags: rec[8 * i + 1], flow: meta.flows[rec[8 * i + 2]], op: rec[8 * i + 3] === 255 ? null : meta.ops[rec[8 * i + 3]], target: view.getUint32(8 * i + 4) }
  let got: { length: number; flags: number; flow: string; op: string | null; target: number }
  try {
    const ins = decodeColdFire(read(a), a)
    got = { length: ins.length, flags: ins.flags, flow: ins.flow, op: ins.op, target: ins.target === undefined ? 0xffffffff : ins.target }
  } catch (e) {
    if (!(e instanceof RangeError)) throw e
    got = { length: 0, flags: 0, flow: 'none', op: null, target: 0 }
  }
  if (got.length !== want.length || got.flags !== want.flags || got.flow !== want.flow || got.op !== want.op || got.target !== want.target) {
    if (diffs++ < 10) console.log(`0x${a.toString(16)}: python ${JSON.stringify(want)}, ts ${JSON.stringify(got)}`)
  }
}
console.log(`${dev.name} ${meta.os}: ${meta.n} offsets, ${diffs} differ (${((performance.now() - t0) / 1000).toFixed(1)} s)`)
process.exitCode = diffs ? 1 : 0
