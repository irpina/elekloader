// SPDX-License-Identifier: GPL-3.0-or-later
// What a site's build page does around the builder, the same on every site: load a selection from the catalog and
// check it, follow a build in three steps, and keep its log as text for a bug report.
import { planBuild, type Catalog } from './catalog.ts'
import type { Builder } from './client.ts'
import type { BuildResult, Check, Device, Ready } from './protocol.ts'

export type Prepared =
  | { ok: true; enabled: string[]; check: Check; device: Device }
  | { ok: false; error: string; device?: Device; check?: Check }

/** The owner's stock file and a selection of catalog mod ids, loaded and checked: the stock file must be the device
 * and OS asked for, each mod comes from the catalog with what it requires, and the core is the plan's. */
export async function prepare(builder: Builder, input: { catalog: Catalog; device: string; os: string; stock: Blob & { name: string }; ids: readonly string[] }): Promise<Prepared> {
  const plan = planBuild(input.catalog, input.device, input.os, input.ids)
  if (!plan.core) return { ok: false, error: `The catalog has no core for ${input.device} OS ${input.os}.` }
  if (plan.missing.length) return { ok: false, error: `Not available for OS ${input.os}: ${plan.missing.join(', ')}.` }
  await builder.load()
  const stock = await builder.setStock(input.stock)
  if (!stock.ok) return { ok: false, error: stock.error }
  if (stock.dev.key !== input.device || stock.os !== input.os)
    return { ok: false, error: `This OS file is ${stock.device} ${stock.os}, not the ${input.device} OS ${input.os} chosen.`, device: stock.dev }
  let enabled: string[] = []
  for (const mod of plan.mods) {
    const added = await builder.addCatalogMod(mod.file)
    if (!added.ok) return { ok: false, error: added.error, device: stock.dev }
    enabled = await builder.tick(enabled, added.mod.path)
  }
  // the plan's core, in place of any other the ticks chose (a build has one core)
  const cores = (await builder.mods()).filter(m => m.builtin && m.id === 'core')
  const core = cores.find(m => m.file === plan.core!.file)
  if (!core || !core.fits) return { ok: false, error: `${plan.core.file} does not fit this OS file.`, device: stock.dev }
  enabled = [...enabled.filter(p => !cores.some(c => c.path === p)), core.path].sort()
  const check = await builder.check(enabled)
  return check.ok ? { ok: true, enabled, check, device: stock.dev } : { ok: false, error: check.headline ?? 'These mods cannot be built together.', check, device: stock.dev }
}

/** The three steps a build page shows (link the mods, pack the OS, verify the file), from the builder's log: its
 * "linked" line ends the first, "packed" the second. Other lines stay in the step they are in. */
export type Step = 'composing' | 'packing' | 'verifying'
export function buildStep(line: string, step: Step = 'composing'): Step {
  return line.startsWith('linked ') ? 'packing' : line.startsWith('packed ') ? 'verifying' : step
}

/** The builder, in a line: the engine, the kit's protocol and the catalog, from init's reply. */
export function describeBuilder(ready: Ready) {
  return `elekloader ${ready.engine} (kit protocol ${ready.protocol}), catalog ${ready.catalog.revision}`
}

/** A build's log as a text file for a bug report: what was built and by which builder, then every line with its
 * time. It names no stock file and holds no firmware. `title` names the site's report, if it wants. */
export function buildLogText(input: { title?: string; builder: string; device: string; os: string; version: string; enabled: readonly string[]; result: BuildResult }) {
  const { result } = input
  const lines = [
    `${input.title ?? 'elekloader build log'}: ${input.device}, OS ${input.os}`,
    `Builder: ${input.builder}`,
    `Mods: ${result.ok ? result.mods.join(', ') : input.enabled.map(p => p.split('/').pop()).join(', ')}`,
    `OS version shown: ${input.version}`,
    result.ok ? `Result: built and verified in ${result.seconds.toFixed(2)} s` : `Result: failed: ${result.error}`,
    ...(result.ok ? result.files.map(f => `  ${f.name}  ${f.bytes} bytes  sha256 ${f.sha256}`) : []),
    '',
    ...(result.log ?? []).map(([seconds, line]) => `${seconds.toFixed(2).padStart(7)} s  ${line}`),
  ]
  return lines.join('\n') + '\n'
}
