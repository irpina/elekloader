// SPDX-License-Identifier: GPL-3.0-or-later
// The comparison with elekloader's Python, on your own stock files and mods (none of which go in the repo).
//
//   node tools/parity.ts plan    <config.json> <cases.json>   cases from your files, and broken copies of a mod
//   python3 tools/parity.py      <cases.json>  <py.json>       the Python's results (POSIX; WSL on Windows)
//   node tools/parity.ts compare <cases.json>  <py.json>       this engine's, compared: every file's sha256, every
//                                                              refusal, the log, the live check, every describe
//
// config.json names your files: {"root": "/tmp/elekparity", "map": [["C:/", "/mnt/c/"]], "scratch": "<a folder>",
// "stocks": {"dt153": ..., "dt154": ..., "dt153zip": ..., "dn143": ..., "dn144": ..., "ot": ..., "otbin": ...},
// "dirs": {"dt": ..., "release": ..., "octabam": ..., "dtmod": ...}, "files": {"octatrick": ..., "bundle": ...}}.
// Both sides see each file under the same path (root/<case>/stock/<name>, root/<case>/mods/<name>), so the
// manifests, which name those paths, must match byte for byte too.
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { LoaderModel, Store } from '../src/model.ts'
import { PatchError, build, save } from '../src/patch.ts'
import { sha } from '../src/bytes.ts'
import { dumps } from '../src/py.ts'

type Case = { n: number; label: string; stock: string; stock_local: string; stock_name: string; mods: string[]; mods_local: string[]
  version: string | null; check_only?: boolean; out_name: string }

const [, , mode, a, b] = process.argv

function plan(configPath: string, casesPath: string) {
  const cfg = JSON.parse(readFileSync(configPath, 'utf8'))
  const toPy = (p: string) => cfg.map.reduce((s: string, [x, y]: [string, string]) => (s.startsWith(x) ? y + s.slice(x.length) : s), p.replace(/\\/g, '/'))
  const dir = (k: string) => cfg.dirs[k] as string
  const f = (k: string, name: string) => join(dir(k), name)
  const cases: Case[] = []
  const add = (label: string, stockKey: string, mods: string[], version: string | null = 'TEST', extra: Partial<Case> = {}) => {
    const stock = cfg.stocks[stockKey]
    cases.push({ n: cases.length, label, stock: toPy(stock), stock_local: stock, stock_name: basename(stock), mods: mods.map(toPy),
      mods_local: mods, version, out_name: 'out.syx', ...extra })
  }
  const dtMods = readdirSync(dir('dt')).filter(n => n.endsWith('.elemod') && !n.startsWith('core') && !n.includes('-os1.54'))
  for (const core of ['core-2.0a.elemod', 'core-2.1.elemod']) {
    for (const m of dtMods) add(`dt153 ${core} + ${m}`, 'dt153', [f('dt', core), f('dt', m)])
  }
  const three = ['digislicer-2.1.elemod', 'digineighbor-0.6.elemod', 'digihealth-1.0.elemod']
  for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) add(`dt153 core-2.1 + ${three[i]} + ${three[j]}`, 'dt153', [f('dt', 'core-2.1.elemod'), f('dt', three[i]), f('dt', three[j])])
  add('dt153 core-2.1 + all three', 'dt153', [f('dt', 'core-2.1.elemod'), ...three.map(m => f('dt', m))])
  const os154 = readdirSync(dir('dt')).filter(n => n.endsWith('-os1.54.elemod') && !n.startsWith('core'))
  for (const m of os154) add(`dt154 + ${m}`, 'dt154', [f('dt', 'core-2.1-os1.54.elemod'), f('dt', m)])
  add('dt154 all', 'dt154', [f('dt', 'core-2.1-os1.54.elemod'), ...os154.map(m => f('dt', m))])
  add('dt154 core alone', 'dt154', [f('dt', 'core-2.1-os1.54.elemod')])
  const dtmods = readdirSync(dir('dtmod')).filter(n => n.endsWith('.dtmod') && !n.startsWith('core'))
  for (const m of dtmods) add(`dt153 .dtmod ${m}`, 'dt153', [f('dtmod', 'core-2.0a.dtmod'), f('dtmod', m)])
  add('dt153 .dtmod all', 'dt153', [f('dtmod', 'core-2.0a.dtmod'), ...dtmods.map(m => f('dtmod', m))])
  add('dt153 whole-build bundle', 'dt153', [cfg.files.bundle], null)
  add('dt153 bundle + core (format mix)', 'dt153', [cfg.files.bundle, f('dt', 'core-2.1.elemod')])
  add('dt153 no version', 'dt153', [f('dt', 'core-2.1.elemod')], null)
  add('dt153 version too long', 'dt153', [f('dt', 'core-2.1.elemod')], 'TOOLONG')
  add('dt153 zip', 'dt153zip', [f('dt', 'core-2.1.elemod'), f('dt', 'digislicer-2.1.elemod')])
  add('dt154 zip', 'dt154zip', [f('dt', 'core-2.1-os1.54.elemod')])
  add('dt153 + a 1.54 mod', 'dt153', [f('dt', 'core-2.1.elemod'), f('dt', 'digislicer-2.1-os1.54.elemod')])
  add('dt153 without core', 'dt153', [f('dt', 'digislicer-2.1.elemod')])
  add('dt153 two cores', 'dt153', [f('dt', 'core-2.0a.elemod'), f('dt', 'core-2.1.elemod')])
  add('dt153 check only', 'dt153', [f('dt', 'core-2.1.elemod'), f('dt', 'digislicer-2.1.elemod')], 'TEST', { check_only: true })
  add('dt153 no mods', 'dt153', [])
  add('dn143 core + digihealth 1.1', 'dn143', [f('release', 'core-dn1-2.0a.elemod'), f('release', 'digihealth-1.1.elemod')])
  add('dn143 core alone', 'dn143', [f('release', 'core-dn1-2.0a.elemod')])
  add('dn144 core alone', 'dn144', [f('release', 'core-dn1-2.0a-os1.44.elemod')])
  add('dn143 zip', 'dn143zip', [f('release', 'core-dn1-2.0a.elemod')])
  add('ot octatrick', 'ot', [cfg.files.octatrick], 'TEST')
  add('ot octatrick, no version', 'ot', [cfg.files.octatrick], null)
  add('ot octatrick from the .bin', 'otbin', [cfg.files.octatrick], '1.40X ELEK')
  add('ot zip octatrick', 'otzip', [cfg.files.octatrick], 'T')
  const ob = readdirSync(dir('octabam')).filter(n => n.startsWith('octabam-') && n.endsWith('.elemod'))
  for (const m of ob) add(`ot octabam ${m}`, 'ot', [f('octabam', 'core-0.1.elemod'), f('octabam', m)])
  add('ot octabam all', 'ot', [f('octabam', 'core-0.1.elemod'), ...ob.map(m => f('octabam', m))])
  add('ot core-ot 0.1 + tuner', 'ot', [f('release', 'core-ot-0.1.elemod'), f('octabam', 'octabam-tuner-363861e.elemod')])

  // broken copies of a real mod: every refusal must read the same
  const scratch = cfg.scratch
  mkdirSync(scratch, { recursive: true })
  const base = readFileSync(f('dt', 'digislicer-2.1.elemod'))
  const doc = () => JSON.parse(base.toString('utf8'))
  const muts: [string, (d: any) => any][] = [
    ['elemod-3', d => { d.elemod = 3; return d }],
    ['elemod-true', d => { d.elemod = true; return d }],
    ['extra-field', d => { d.extra = 1; return d }],
    ['no-target', d => { delete d.target; return d }],
    ['target-len', d => { d.target.section3_len = 5; return d }],
    ['align-3', d => { d.sections['.run'].align = 3; return d }],
    ['align-hex', d => { d.sections['.run'].align = '0x10'; return d }],
    ['align-010', d => { d.sections['.run'].align = '010'; return d }],
    ['align-null', d => { d.sections['.run'].align = null; return d }],
    ['new-zz', d => { d.sites[0].new = 'zz'; return d }],
    ['site-len', d => { d.sites[0].len = d.sites[0].len + 2; return d }],
    ['site-kind', d => { d.sites[0].kind = 'other'; return d }],
    ['site-sha', d => { d.sites[0].stock_sha256 = 'ab'; return d }],
    ['site-stock', d => { d.sites[0].stock_sha256 = '0'.repeat(64); return d }],
    ['reloc-type', d => { d.relocs[0][2] = 'abs16'; return d }],
    ['reloc-target', d => { d.relocs[0][3] = 'bad'; return d }],
    ['reloc-short', d => { d.relocs[0] = d.relocs[0].slice(0, 3); return d }],
    ['symbol-shape', d => { d.symbols[Object.keys(d.symbols)[0]] = 5; return d }],
    ['symbol-section', d => { d.symbols[Object.keys(d.symbols)[0]] = ['.fast', 0]; return d }],
    ['export-missing', d => { d.exports.push('nothing_here'); return d }],
    ['weak-not-imported', d => { d.weak = ['zz']; return d }],
    ['requires-missing', d => { d.requires = ['core', 'absent']; return d }],
    ['requires-string', d => { d.requires = 'core'; return d }],
    ['conflicts-core', d => { d.conflicts = ['core']; return d }],
    ['region-outside', d => { d.resources.regions = [{ name: 'r', lo: '0x10', hi: '0x20' }]; return d }],
    ['region-empty', d => { d.resources.regions = [{ name: 'r', lo: '0x20', hi: '0x10' }]; return d }],
    ['resources-empty-list', d => { d.resources = []; return d }],
    ['resources-list', d => { d.resources = [1]; return d }],
    ['sites-null', d => { d.sites = null; return d }],
    ['id-number', d => { d.id = 7; return d }],
    ['contribute-order-str', d => { d.contribute[0].order = '0x20'; return d }],
    ['contribute-no-to', d => { delete d.contribute[0].to; return d }],
    ['contribute-reloc', d => { d.contribute[0].relocs = [[1, 'abs32', 'sym:x', 0]]; return d }],
    ['claim-overlap', d => { d.contribute[0].claims = [['0x40000500', '0x40000510'], ['0x40000508', '0x40000518']]; return d }],
    ['sections-list', d => { d.sections = []; return d }],
    ['section-unknown', d => { d.sections['.data'] = { len: 0 }; return d }],
    ['bss-no-size', d => { delete d.sections['.bss'].size; return d }],
    ['run-len', d => { d.sections['.run'].len = 3; return d }],
    ['part-bad', d => { d.sections['.run'].parts.push(['xyz', 1]); return d }],
    ['part-stock-out', d => { d.sections['.run'].parts.push(['stock', '0x10', 4]); return d }],
    ['collections-entry', d => { d.collections = { dsl_t: { entry: 6 } }; return d }],
    ['copied-site', d => { d.copied = [{ lo: '0x40000400', hi: '0x40400000', to: '0x80000000' }]; return d }],
    ['dup-name', d => { d.resources.names = ['machine:5', 'machine:5']; return d }],
    ['needs-core-3', d => { d.resources.core = '3.0'; return d }],
    ['needs-core-2.0a', d => { d.resources.core = '2.0a'; return d }],
    ['needs-core-number', d => { d.resources.core = 3; return d }],
    ['needs-core-word', d => { d.resources.core = 'three'; return d }],
  ]
  const raw: [string, Buffer][] = [
    ['not-json', Buffer.from('garbage{')],
    ['bad-utf8', Buffer.from([0x7b, 0xff, 0xfe, 0x7d])],
    ['truncated-utf8', Buffer.from([0x7b, 0x22, 0xe2, 0x82])],
    ['bom', Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), base])],
    ['trailing-comma', Buffer.from('{"elemod": 2,}')],
    ['trailing-comma-list', Buffer.from('{"elemod": [2,]}')],
    ['extra-data', Buffer.from('{"elemod": 2} x')],
    ['nan', Buffer.from(base.toString('utf8').replace('"signature": null', '"signature": NaN'))],
    ['float-align', Buffer.from(base.toString('utf8').replace('"align": 4', '"align": 4.0'))],
    ['float-elemod', Buffer.from(base.toString('utf8').replace('"elemod": 2', '"elemod": 2.0'))],
    ['bad-escape', Buffer.from('{"id": "a\\qb"}')],
    ['control-char', Buffer.from('{"id": "a\u0001b"}')],
    ['unterminated', Buffer.from('{"id": "abc')],
    ['no-colon', Buffer.from('{"id" 1}')],
    ['empty', Buffer.from('')],
  ]
  for (const [name, fn] of muts) raw.push([name, Buffer.from(JSON.stringify(fn(doc()), null, 1))])
  for (const [name, data] of raw) {
    const p = join(scratch, `mut-${name}.elemod`)
    writeFileSync(p, data)
    add(`mutation ${name}`, 'dt153', [f('dt', 'core-2.1.elemod'), p])
  }
  // core 3.0 (files.core3 and files.core3_154, optional): with core 2.1's mods, and with a mod that needs it
  if (cfg.files.core3) {
    const c3 = cfg.files.core3 as string
    add('dt153 core-3.0 alone', 'dt153', [c3])
    for (const m of dtMods) add(`dt153 core-3.0 + ${m}`, 'dt153', [c3, f('dt', m)])
    add('dt153 core-3.0 + all three', 'dt153', [c3, ...three.map(m => f('dt', m))])
    add('dt153 core-3.0 + a mod that needs it', 'dt153', [c3, join(scratch, 'mut-needs-core-3.elemod')])
    add('dt153 core-3.0 and core-2.1', 'dt153', [c3, f('dt', 'core-2.1.elemod')])
  }
  if (cfg.files.core3_154) {
    add('dt154 core-3.0 alone', 'dt154', [cfg.files.core3_154])
    add('dt154 core-3.0 all', 'dt154', [cfg.files.core3_154, ...os154.map(m => f('dt', m))])
  }
  writeFileSync(casesPath, JSON.stringify({ root: cfg.root, cases }, null, 1))
  console.log(`${cases.length} cases -> ${casesPath}`)
}

/** JSON-comparable form: key order ignored (Python dicts and JS objects differ there only where noted). */
function canon(v: unknown): unknown {
  if (v instanceof Map) v = Object.fromEntries(v)
  if (Array.isArray(v)) return v.map(canon)
  if (v && typeof v === 'object') return Object.fromEntries(Object.keys(v).sort().map(k => [k, canon((v as any)[k])]))
  return v
}
const same = (x: unknown, y: unknown) => JSON.stringify(canon(x)) === JSON.stringify(canon(y))

async function runTs(c: Case, root: string) {
  const work = `${root}/${c.n}`
  const stockPath = `${work}/stock/${c.stock_name}`
  const stock = { path: stockPath, data: new Uint8Array(readFileSync(c.stock_local)) }
  const mods = c.mods_local.map(p => ({ path: `${work}/mods/${basename(p)}`, data: new Uint8Array(readFileSync(p)) }))
  const out: Record<string, any> = { n: c.n }
  const log: string[] = []
  try {
    const [outputs, man] = await build(stock, mods, c.version, !!c.check_only, line => log.push(line))
    if (!outputs) {
      out.checked = JSON.parse(dumps(man))
    } else {
      const files = save(outputs, man, `${work}/out/${c.out_name}`)
      out.files = Object.fromEntries(files.map(fl => [basename(fl.path), sha(fl.data)]).sort())
      out._files = files
    }
  } catch (e) {
    if (e instanceof PatchError) out.refused = e.message
    else { out.crash = (e as Error).constructor.name.replace(/_$/, ''); out.trace = String((e as Error).stack).slice(0, 400) }
  }
  out.log = log.filter(x => !x.startsWith('packed the main OS'))
  const store = new Store()
  store.write(stockPath, stock.data)
  for (const m of mods) store.write(m.path, m.data)
  const model = new LoaderModel(store, `${work}/mods`)
  out.stock = await model.setStock(stockPath)
  try {
    const r = model.check(mods.map(m => m.path).sort())
    delete r.ms
    out.check = JSON.parse(JSON.stringify(r))
  } catch (e) {
    out.check = { crash: (e as Error).constructor.name.replace(/_$/, '') }
  }
  out.describe = {}
  for (const m of mods) {
    try {
      out.describe[basename(m.path)] = JSON.parse(dumps(model.describe(m.path)))
    } catch (e) {
      out.describe[basename(m.path)] = { crash: (e as Error).constructor.name.replace(/_$/, '') }
    }
  }
  return out
}

async function compare(casesPath: string, pyPath: string) {
  const spec = JSON.parse(readFileSync(casesPath, 'utf8'))
  const py = JSON.parse(readFileSync(pyPath, 'utf8')) as Record<string, any>[]
  let ok = 0
  const bad: string[] = []
  const t0 = Date.now()
  for (const c of spec.cases as Case[]) {
    const p = py[c.n], t = await runTs(c, spec.root)
    const diffs: string[] = []
    for (const k of ['files', 'refused', 'checked', 'log', 'check', 'describe']) {
      if (!same(p[k], t[k])) diffs.push(k)
    }
    if (!!p.crash !== !!t.crash) diffs.push(`crash (${p.crash ?? '-'} / ${t.crash ?? '-'})`)
    const sp = { ...p.stock }, st = { ...t.stock }
    if (!same(sp, st)) diffs.push('stock')
    const state = p.files ? 'built' : p.checked ? 'checked' : p.refused !== undefined ? 'refused' : 'crash'
    if (diffs.length) {
      bad.push(`#${c.n} ${c.label}: ${diffs.join(', ')}`)
      const dump = join(process.env.PARITY_DIFFS ?? '.', `diff-${c.n}.json`)
      writeFileSync(dump, JSON.stringify({ label: c.label, py: p, ts: { ...t, _files: undefined } }, null, 1))
      if (t._files && process.env.PARITY_DIFFS) for (const fl of t._files) writeFileSync(join(process.env.PARITY_DIFFS, `ts-${c.n}-${basename(fl.path)}`), fl.data)
    } else ok++
    console.log(`${diffs.length ? 'DIFF' : 'same'} ${state.padEnd(7)} #${c.n} ${c.label}${diffs.length ? '  [' + diffs.join(', ') + ']' : ''}`)
  }
  console.log(`\n${ok} of ${spec.cases.length} cases the same (${((Date.now() - t0) / 1000).toFixed(1)} s for the TypeScript side)`)
  if (bad.length) { console.log(bad.join('\n')); process.exitCode = 1 }
}

if (mode === 'plan') plan(a, b)
else if (mode === 'compare') await compare(a, b)
else { console.error('node tools/parity.ts plan <config.json> <cases.json> | compare <cases.json> <py.json>'); process.exit(2) }
