// SPDX-License-Identifier: GPL-3.0-or-later
// src/*.ts -> dist/*.js for a page or a worker with no build step of its own: Node's own type stripping (nothing to
// install), with each relative '.ts' import pointed at its '.js'. A bundler (Vite, esbuild) can take src/ as it is.
//
//   node tools/build.ts [out dir, default dist]
import { mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'src')
const out = process.argv[2] ?? join(root, 'dist')

function files(dir: string): string[] {
  return readdirSync(dir).flatMap(n => (statSync(join(dir, n)).isDirectory() ? files(join(dir, n)) : n.endsWith('.ts') ? [join(dir, n)] : []))
}

rmSync(out, { recursive: true, force: true })
let n = 0, bytes = 0
for (const f of files(src)) {
  const js = stripTypeScriptTypes(readFileSync(f, 'utf8'), { mode: 'strip' })
    .replace(/(from\s+|import\s*\(\s*)(['"])(\.{1,2}\/[^'"]+)\.ts\2/g, '$1$2$3.js$2')
  const to = join(out, relative(src, f)).replace(/\.ts$/, '.js')
  mkdirSync(dirname(to), { recursive: true })
  writeFileSync(to, js)
  n++
  bytes += js.length
}
console.log(`${n} files, ${(bytes / 1024).toFixed(0)} KB -> ${out}`)
