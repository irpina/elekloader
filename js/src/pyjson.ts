// SPDX-License-Identifier: GPL-3.0-or-later
// Reading a .elemod as elekloader's Python does (raw.decode('utf-8'), then json.loads), so a file is accepted or
// refused alike, with the same message: Python's UTF-8 errors and json's ("Expecting value: line 1 column 1 (char
// 0)"). JSON.parse would differ: it refuses NaN and Infinity, which json accepts, and reads 4.0 as the integer 4,
// which elekloader refuses where it wants an integer. A float is read as a PyFloat for that reason.

import { PyFloat } from './py.ts'

export { PyFloat }

export class JSONDecodeError extends Error {}
export class UnicodeDecodeError extends Error {}

/** bytes.decode('utf-8'), with Python's message at the first bad byte. */
export function decodeUtf8(d: Uint8Array): string {
  const fail = (start: number, end: number, why: string) => {
    throw new UnicodeDecodeError(end > start
      ? `'utf-8' codec can't decode bytes in position ${start}-${end}: ${why}`
      : `'utf-8' codec can't decode byte 0x${d[start].toString(16).padStart(2, '0')} in position ${start}: ${why}`)
  }
  for (let i = 0; i < d.length;) {
    const b = d[i]
    if (b < 0x80) { i++; continue }
    let need: number, lo = 0x80, hi = 0xbf
    if (b >= 0xc2 && b <= 0xdf) need = 1
    else if (b >= 0xe0 && b <= 0xef) { need = 2; if (b === 0xe0) lo = 0xa0; if (b === 0xed) hi = 0x9f }
    else if (b >= 0xf0 && b <= 0xf4) { need = 3; if (b === 0xf0) lo = 0x90; if (b === 0xf4) hi = 0x8f }
    else return fail(i, i, 'invalid start byte')
    for (let k = 1; k <= need; k++) {
      if (i + k >= d.length) return fail(i, d.length - 1, 'unexpected end of data')
      const c = d[i + k]
      if (c < (k === 1 ? lo : 0x80) || c > (k === 1 ? hi : 0xbf)) return fail(i, i + k - 1, 'invalid continuation byte')
    }
    i += need + 1
  }
  // ignoreBOM keeps a leading byte-order mark in the text, as Python's decode does (json.loads then refuses it)
  return new TextDecoder('utf-8', { ignoreBOM: true }).decode(d)
}

const WS = /[ \t\n\r]*/y
const NUMBER = /(-?(?:0|[1-9][0-9]*))(\.[0-9]+)?([eE][-+]?[0-9]+)?/y

/** json.loads(s): Python's decoder, its messages included. */
export function loads(s: string): unknown {
  const err = (msg: string, pos: number): never => {
    const line = s.slice(0, pos).split('\n').length
    const col = pos - s.lastIndexOf('\n', pos - 1)
    throw new JSONDecodeError(`${msg}: line ${line} column ${col} (char ${pos})`)
  }
  if (s.startsWith('﻿')) err('Unexpected UTF-8 BOM (decode using utf-8-sig)', 0)
  const ws = (i: number) => { WS.lastIndex = i; WS.exec(s); return WS.lastIndex }

  function str(start: number): [string, number] {          // start: just after the opening quote
    let out = '', i = start
    for (;;) {
      if (i >= s.length) err('Unterminated string starting at', start - 1)
      const c = s[i]
      if (c === '"') return [out, i + 1]
      if (c === '\\') {
        const e = s[i + 1]
        if (e === undefined) err('Unterminated string starting at', start - 1)
        const simple: Record<string, string> = { '"': '"', '\\': '\\', '/': '/', b: '\b', f: '\f', n: '\n', r: '\r', t: '\t' }
        if (e in simple) { out += simple[e]; i += 2; continue }
        if (e !== 'u') err('Invalid \\escape', i)       // CPython's C scanner: no character named
        const hex4 = (at: number) => {
          const h = s.slice(at, at + 4)
          if (!/^[0-9a-fA-F]{4}$/.test(h)) err('Invalid \\uXXXX escape', at - 1)
          return parseInt(h, 16)
        }
        let u = hex4(i + 2)
        i += 6
        if (u >= 0xd800 && u <= 0xdbff && s[i] === '\\' && s[i + 1] === 'u') {
          const v = hex4(i + 2)
          if (v >= 0xdc00 && v <= 0xdfff) { out += String.fromCharCode(u, v); i += 6; continue }
        }
        out += String.fromCharCode(u)
        continue
      }
      if (c.charCodeAt(0) < 0x20) err('Invalid control character at', i)
      out += c
      i++
    }
  }

  function value(i: number): [unknown, number] {
    const c = s[i]
    if (c === '"') return str(i + 1)
    if (c === '{') return object(i + 1)
    if (c === '[') return array(i + 1)
    if (c === 'n' && s.startsWith('null', i)) return [null, i + 4]
    if (c === 't' && s.startsWith('true', i)) return [true, i + 4]
    if (c === 'f' && s.startsWith('false', i)) return [false, i + 5]
    if (c === 'N' && s.startsWith('NaN', i)) return [new PyFloat(NaN), i + 3]
    if (c === 'I' && s.startsWith('Infinity', i)) return [new PyFloat(Infinity), i + 8]
    if (c === '-' && s.startsWith('-Infinity', i)) return [new PyFloat(-Infinity), i + 9]
    NUMBER.lastIndex = i
    const m = NUMBER.exec(s)
    if (m) {
      const end = i + m[0].length
      if (m[2] || m[3]) return [new PyFloat(Number(m[0])), end]
      return [Number(m[1]), end]
    }
    return err('Expecting value', i)
  }

  function object(start: number): [unknown, number] {
    const out: Record<string, unknown> = {}
    let i = ws(start)
    if (s[i] === '}') return [out, i + 1]
    for (;;) {
      if (s[i] !== '"') err('Expecting property name enclosed in double quotes', i)
      const [k, a] = str(i + 1)
      i = ws(a)
      if (s[i] !== ':') err("Expecting ':' delimiter", i)
      i = ws(i + 1)
      const [v, b] = value(i)
      out[k] = v
      i = ws(b)
      if (s[i] === '}') return [out, i + 1]
      if (s[i] !== ',') err("Expecting ',' delimiter", i)
      const comma = i
      i = ws(i + 1)
      if (s[i] === '}') err('Illegal trailing comma before end of object', comma)
    }
  }

  function array(start: number): [unknown, number] {
    const out: unknown[] = []
    let i = ws(start)
    if (s[i] === ']') return [out, i + 1]
    for (;;) {
      const [v, b] = value(i)
      out.push(v)
      i = ws(b)
      if (s[i] === ']') return [out, i + 1]
      if (s[i] !== ',') err("Expecting ',' delimiter", i)
      const comma = i
      i = ws(i + 1)
      if (s[i] === ']') err('Illegal trailing comma before end of array', comma)
    }
  }

  const [v, end] = value(ws(0))
  const rest = ws(end)
  if (rest !== s.length) err('Extra data', rest)
  return v
}
