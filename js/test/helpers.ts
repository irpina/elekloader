// SPDX-License-Identifier: GPL-3.0-or-later
// What the tests share.

/** tools/vectors.py's generator. */
export function lcg(seed: number, n: number): Uint8Array {
  const out = new Uint8Array(n)
  let s = seed >>> 0
  for (let i = 0; i < n; i++) {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0
    out[i] = s >>> 24
  }
  return out
}
