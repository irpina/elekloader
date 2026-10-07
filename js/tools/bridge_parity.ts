// SPDX-License-Identifier: GPL-3.0-or-later
// The web page's calls, compared with web/bridge.py: sessions of the calls a page makes (the site's cores, a stock
// file, mods from the shop and the user's own, ticking, the live check, the version field, building, removing),
// played through both, every reply compared. This is the contract a page (elekloader's, modwerk's) relies on.
//
//   node tools/bridge_parity.ts plan    <config.json> <sessions.json>   (config: tools/parity.ts's)
//   python3 tools/bridge_parity.py      <sessions.json> <py.json>
//   node tools/bridge_parity.ts compare <sessions.json> <py.json>
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { Bridge } from '../src/bridge.ts'
import { sha } from '../src/bytes.ts'

type Step = { call: string; args?: Record<string, unknown>; file?: string; file_local?: string; sha?: boolean }
type Session = { label: string; steps: Step[] }
const [, , mode, a, b] = process.argv

function plan(configPath: string, outPath: string) {
  const cfg = JSON.parse(readFileSync(configPath, 'utf8'))
  const toPy = (p: string) => cfg.map.reduce((s: string, [x, y]: [string, string]) => (s.startsWith(x) ? y + s.slice(x.length) : s), p.replace(/\\/g, '/'))
  const rel = cfg.dirs.release, dt = cfg.dirs.dt, ob = cfg.dirs.octabam, dtmod = cfg.dirs.dtmod
  const file = (p: string) => ({ file: toPy(p), file_local: p })
  const cores = readdirSync(rel).filter(n => n.startsWith('core-')).sort()
  const site = (): Step[] => [{ call: 'info' }, ...cores.map(n => ({ call: 'add_core', args: { name: n }, sha: true, ...file(join(rel, n)) }))]
  const stock = (k: string, name?: string): Step => ({ call: 'set_stock', args: { name: name ?? basename(cfg.stocks[k]) }, ...file(cfg.stocks[k]) })
  const mod = (p: string, shop = false, name?: string): Step => ({ call: 'add_mod', args: { name: name ?? basename(p) }, sha: shop, ...file(p) })
  const M = (n: string) => '/work/mods/' + n, C = (n: string) => '/work/core/' + n
  const flow = (label: string, st: Step, mods: Step[], tickPaths: string[], version: string, extra: Step[] = []): Session => {
    const steps: Step[] = [...site(), st, ...mods, { call: 'mods' }]
    for (const p of tickPaths) steps.push({ call: 'tick', args: { enabled: '$ticked', path: p } })   // the set the last tick gave
    steps.push({ call: 'check', args: { enabled: '$ticked' } }, { call: 'version', args: { version, enabled: '$ticked' } },
      { call: 'version', args: { version: 'ünï', enabled: '$ticked' } }, { call: 'version', args: { version: 'TOOLONGVERSION', enabled: '$ticked' } },
      { call: 'version', args: { version: '', enabled: '$ticked' } },
      { call: 'build', args: { enabled: '$ticked', version, name: 'my build' } }, ...extra)
    return { label, steps }
  }
  const sessions: Session[] = [
    flow('dt153: the shop\'s mods', stock('dt153'),
      ['digislicer-2.1.elemod', 'digineighbor-0.6.elemod', 'digihealth-1.0.elemod'].map(n => mod(join(rel, n), true)),
      [M('digislicer-2.1.elemod'), M('digineighbor-0.6.elemod')], '2.0a',
      [{ call: 'remove_mod', args: { path: M('digineighbor-0.6.elemod') } }, { call: 'mods' }, { call: 'check', args: { enabled: [C('core-2.1.elemod'), M('digislicer-2.1.elemod')] } }]),
    flow('dt154: the shop\'s mods', stock('dt154'),
      ['digislicer-2.1-os1.54.elemod', 'digihealth-1.0-os1.54.elemod'].map(n => mod(join(rel, n), true)),
      [M('digislicer-2.1-os1.54.elemod'), M('digihealth-1.0-os1.54.elemod')], 'DS21'),
    flow('dt153 zip: own mods, old and new', stock('dt153zip'),
      [mod(join(dt, 'digislicer-1.3.elemod')), mod(join(dt, 'neighbor-0.5.elemod')), mod(join(dt, 'core-2.0a.elemod'))],
      [M('digislicer-1.3.elemod'), M('neighbor-0.5.elemod')], '2.0a'),
    flow('dt153: legacy .dtmod files', stock('dt153'),
      ['core-2.0a.dtmod', 'slicer-2.0a.dtmod', 'fast-audio-2.0a.dtmod', 'sysinfo-2.0a.dtmod'].map(n => mod(join(dtmod, n))),
      [M('slicer-2.0a.dtmod'), M('fast-audio-2.0a.dtmod')], '2.0a'),
    flow('dt153: the whole-build bundle', stock('dt153'), [mod(cfg.files.bundle)], [M(basename(cfg.files.bundle))], '1.8F'),
    flow('dn143: digihealth 1.1', stock('dn143'), [mod(join(rel, 'digihealth-1.1.elemod'), true)], [M('digihealth-1.1.elemod')], '2.0a'),
    flow('dn144 zip: core alone', stock('dn143zip', 'Digitone.zip'), [], [C('core-dn1-2.0a.elemod')], '2.0a'),
    flow('ot: octatrick', stock('ot'), [mod(cfg.files.octatrick)], [M(basename(cfg.files.octatrick))], '1.40C ELEK'),
    flow('ot .bin: octabam with its own core', stock('otbin'),
      [mod(join(ob, 'core-0.1.elemod')), mod(join(ob, 'octabam-tuner-363861e.elemod')), mod(join(ob, 'octabam-repitch-363861e.elemod'))],
      [M('octabam-tuner-363861e.elemod'), M('octabam-repitch-363861e.elemod')], 'TUNER'),
    { label: 'refusals', steps: [
      ...site(),
      { call: 'check', args: { enabled: [] } },
      { call: 'version', args: { version: '2.0a', enabled: [] } },
      { call: 'build', args: { enabled: [], version: '2.0a', name: 'x' } },
      { call: 'set_stock', args: { name: 'not-an-os.syx' }, ...file(join(rel, 'digislicer-2.1.elemod')) },
      { call: 'set_stock', args: { name: '..' }, ...file(join(rel, 'digislicer-2.1.elemod')) },
      stock('dt153', 'C:\\fakepath\\Digitakt_OS1.53.syx'),
      { call: 'add_mod', args: { name: 'readme.txt' }, ...file(join(rel, 'digislicer-2.1.elemod')) },
      { call: 'add_mod', args: { name: 'digislicer-2.1.elemod', sha256: '0'.repeat(64) }, ...file(join(rel, 'digislicer-2.1.elemod')) },
      ...readdirSync(cfg.scratch).filter(n => n.startsWith('mut-')).sort().map(n => mod(join(cfg.scratch, n))),
      { call: 'mods' },
      mod(join(rel, 'digislicer-2.1-os1.54.elemod')),
      { call: 'tick', args: { enabled: [], path: M('digislicer-2.1-os1.54.elemod') } },
      { call: 'check', args: { enabled: [M('digislicer-2.1-os1.54.elemod')] } },
      { call: 'check', args: { enabled: [C('core-2.1.elemod'), C('core-2.1-os1.54.elemod')] } },
      { call: 'remove_mod', args: { path: C('core-2.1.elemod') } },
      { call: 'remove_mod', args: { path: M('absent.elemod') } },
      { call: 'build', args: { enabled: [C('core-2.1.elemod')], version: 'ünï', name: 'x' } },
      { call: 'build', args: { enabled: [C('core-2.1.elemod'), M('digislicer-2.1-os1.54.elemod')], version: '2.0a', name: 'x.SYX' } },
      { call: 'nope' },
    ] },
  ]
  // core 3.0 beside core 2.1 (files.core3, optional): a mod that needs nothing from it ticks 2.1, one that needs it
  // (tools/parity.ts's mut-needs-core-3, in the scratch folder) moves the build to 3.0
  if (cfg.files.core3) {
    sessions.push(flow('dt153: core 3.0 beside core 2.1', stock('dt153'),
      [{ call: 'add_core', args: { name: 'core-3.0.elemod' }, sha: true, ...file(cfg.files.core3) },
        mod(join(rel, 'digihealth-1.0.elemod'), true), mod(join(cfg.scratch, 'mut-needs-core-3.elemod'))],
      [M('digihealth-1.0.elemod'), M('mut-needs-core-3.elemod')], 'C300'))
  }
  writeFileSync(outPath, JSON.stringify({ sessions }, null, 1))
  console.log(`${sessions.length} sessions, ${sessions.reduce((n, s) => n + s.steps.length, 0)} calls -> ${outPath}`)
}

/** As bridge_parity.py's normalize: no timings, and the log's lines only. */
function normalize(r: any): any {
  if (Array.isArray(r)) return r.map(normalize)
  if (r && typeof r === 'object' && !(r instanceof Uint8Array)) {
    const o: Record<string, any> = {}
    for (const [k, v] of Object.entries(r)) if (k !== 'ms' && k !== 'seconds' && k !== 'data') o[k] = normalize(v)
    if (Array.isArray(o.log)) o.log = r.log.map((x: [number, string]) => x[1]).filter((x: string) => !x.startsWith('packed the main OS'))
    return o
  }
  return r
}

const canon = (v: unknown): unknown => (Array.isArray(v) ? v.map(canon) : v && typeof v === 'object'
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canon((v as any)[k])])) : v)

async function play(s: Session) {
  const br = new Bridge()
  const replies: unknown[] = []
  let ticked: string[] = []
  for (const step of s.steps) {
    const raw = step.file_local ? new Uint8Array(readFileSync(step.file_local)) : undefined
    const args: Record<string, any> = JSON.parse(JSON.stringify(step.args ?? {}))
    if (step.sha && raw) args.sha256 = sha(raw)
    for (const k of Object.keys(args)) if (args[k] === '$ticked') args[k] = ticked
    let r: any
    try {
      r = await br.call(step.call, args, raw)
    } catch (e) {
      r = { exception: (e as Error).constructor.name.replace(/_$/, ''), message: (e as Error).message }
    }
    if (step.call === 'tick' && Array.isArray(r)) ticked = r
    replies.push(normalize(r))
  }
  return replies
}

async function compare(sessionsPath: string, pyPath: string) {
  const { sessions } = JSON.parse(readFileSync(sessionsPath, 'utf8')) as { sessions: Session[] }
  const py = JSON.parse(readFileSync(pyPath, 'utf8'))
  let calls = 0, same = 0
  for (const [i, s] of sessions.entries()) {
    const ts = await play(s)
    const diffs: string[] = []
    s.steps.forEach((step, k) => {
      calls++
      if (JSON.stringify(canon(ts[k])) === JSON.stringify(canon(py[i].replies[k]))) same++
      else diffs.push(`${k} ${step.call}: py ${JSON.stringify(py[i].replies[k]).slice(0, 300)}\n        ts ${JSON.stringify(ts[k]).slice(0, 300)}`)
    })
    console.log(`${diffs.length ? 'DIFF' : 'same'} ${s.label} (${s.steps.length} calls)`)
    for (const d of diffs.slice(0, 6)) console.log('   ' + d)
  }
  console.log(`\n${same} of ${calls} calls give the same reply`)
  if (same !== calls) process.exitCode = 1
}

if (mode === 'plan') plan(a, b)
else if (mode === 'compare') await compare(a, b)
else { console.error('node tools/bridge_parity.ts plan <config.json> <sessions.json> | compare <sessions.json> <py.json>'); process.exit(2) }
