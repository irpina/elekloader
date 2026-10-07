// SPDX-License-Identifier: GPL-3.0-or-later
// The smallest site with elekloader's kit (docs/INTEGRATING.md). It expects the kit's built files at ./elekloader/
// (node js/tools/build.ts js/examples/minimal/elekloader) and a catalog with its files at ./catalog/
// (node js/tools/kit.ts sync <catalog.json> js/examples/minimal/catalog).
import { buildLogText, buildStep, createBuilder, describeBuilder, parseCatalog, prepare } from './elekloader/kit/index.js'

const $ = id => document.getElementById(id)
const builder = createBuilder({
  base: new URL('catalog/', location.href).href,
  worker: () => new Worker(new URL('elekloader/kit/worker.js', location.href), { type: 'module' }),
})
let catalog, ready, stock, device, os, prepared, built

async function start() {
  catalog = parseCatalog(await (await fetch('catalog/catalog.json')).json())
  ready = await builder.load()
  $('status').textContent = `Ready: ${describeBuilder(ready)}.`
}

// the stock file: the builder recognises it by its hash, and the catalog's mods for its device and OS are offered
$('stock').onchange = async () => {
  stock = $('stock').files[0]
  if (!stock) return
  const st = await builder.setStock(stock)
  $('stock-info').textContent = st.ok ? `${st.device}, OS ${st.os}` : st.error
  device = st.ok ? st.dev.key : undefined
  os = st.ok ? st.os : undefined
  const fits = catalog.mods.filter(m => m.device === device && m.os === os)
  $('mods').replaceChildren(...(fits.length ? fits.map(m => {
    const label = document.createElement('label'), box = document.createElement('input')
    box.type = 'checkbox'; box.value = m.id; box.onchange = check
    label.append(box, ` ${m.title} ${m.version}`, Object.assign(document.createElement('small'), { textContent: m.summary ? ` · ${m.summary}` : '' }))
    return label
  }) : [Object.assign(document.createElement('small'), { textContent: st.ok ? 'The catalog has no mods for this OS.' : '' })]))
  await check()
}

// the selection, checked by the builder as it changes
async function check() {
  if (!device) return
  const ids = [...$('mods').querySelectorAll('input:checked')].map(b => b.value)
  prepared = await prepare(builder, { catalog, device, os, stock, ids })
  $('status').textContent = prepared.ok ? `Ready to build: ${prepared.check.order?.join(' › ') ?? ''}` : prepared.error
  $('build').disabled = !prepared.ok
}

$('build').onclick = async () => {
  $('build').disabled = true
  const steps = [...$('steps').children]
  let step = 'composing'
  const show = () => steps.forEach((li, i) => { const at = ['composing', 'packing', 'verifying'].indexOf(step); li.className = i < at ? 'done' : i === at ? 'on' : '' })
  show()
  const version = ready.info.devices.find(d => d.key === device).default_version   // the OS version the unit shows
  const named = await builder.version(version, prepared.enabled)
  built = await builder.build(prepared.enabled, version, named.name, line => { step = buildStep(line, step); show(); $('status').textContent = line })
  steps.forEach(li => { li.className = built.ok ? 'done' : '' })
  $('status').textContent = built.ok ? `Built and verified in ${built.seconds.toFixed(1)} s.` : built.error
  $('result').replaceChildren(...(built.ok ? built.files.map(f => Object.assign(document.createElement('a'), {
    className: 'file', textContent: `${f.name} (${f.bytes} bytes)`, download: f.name,
    href: URL.createObjectURL(new Blob([f.data], { type: 'application/octet-stream' })),
  })) : []))
  $('log').replaceChildren(...(built.log ?? []).map(([t, line]) => {
    const li = document.createElement('li')
    li.append(Object.assign(document.createElement('span'), { textContent: `${t.toFixed(2)} s` }), line)
    return li
  }))
  $('log-box').hidden = !built.log?.length
  $('build').disabled = false
}

$('save-log').onclick = () => {
  const text = buildLogText({ builder: describeBuilder(ready), device: ready.info.devices.find(d => d.key === device).name, os, version: built.ok ? built.version : '', enabled: prepared.enabled, result: built })
  const a = Object.assign(document.createElement('a'), { download: 'build-log.txt', href: URL.createObjectURL(new Blob([text], { type: 'text/plain' })) })
  a.click()
}

start().catch(error => { $('status').textContent = error.message })
