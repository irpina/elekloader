// SPDX-License-Identifier: GPL-3.0-or-later
// One build through the bridge, timed: node tools/smoke.ts <stock> <mod>... (files stay where they are).
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import { Bridge } from '../src/bridge.ts'

const [, , stock, ...mods] = process.argv
const b = new Bridge()
const t0 = performance.now()
const st = await b.setStock({ name: basename(stock) }, new Uint8Array(readFileSync(stock)))
const t1 = performance.now()
console.log('stock:', st.ok ? `${st.device} ${st.os}` : st.error, `(${(t1 - t0).toFixed(0)} ms)`)
for (const m of mods) {
  const r = b.addMod({ name: basename(m) }, new Uint8Array(readFileSync(m)))
  console.log('mod:', r.ok ? r.mod.label : r.error)
}
const enabled = b.mods().filter(d => !d.error).map(d => d.path)
const t2 = performance.now()
const c = b.check({ enabled })
console.log('check:', c.ok ? `ok (${c.order.join(', ')})` : `${c.headline}: ${c.problems.join(' | ')}`, `(${(performance.now() - t2).toFixed(0)} ms)`)
const t3 = performance.now()
const r = await b.build({ enabled, version: 'TEST', name: 'smoke.syx' }, line => console.log('  ' + line))
console.log('build:', r.ok ? r.files.map((f: any) => `${f.name} ${f.bytes} ${f.sha256.slice(0, 16)}`).join(', ') : r.error, `(${(performance.now() - t3).toFixed(0)} ms)`)
