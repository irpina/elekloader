// SPDX-License-Identifier: GPL-3.0-or-later
// The few Python behaviours elekloader's messages and files depend on, so this engine says and writes exactly
// what the Python one does: repr() and str() of JSON values, int(x, 0), and json.dumps.

/** A JSON number with a fraction or an exponent (or NaN, Infinity): a Python float, not an int. pyjson reads
 * floats as these, so 4.0 is refused where elekloader wants an int, as Python refuses it. */
export class PyFloat {
  readonly value: number
  constructor(value: number) { this.value = value }
}

/** The Python exceptions elekloader lets through (it catches only its own): a malformed mod still fails, as there. */
export class PyException extends Error {}
export class TypeError_ extends PyException {}
export class AttributeError extends PyException {}
export class ValueError extends PyException {}
export class KeyError extends PyException {}

/** type(v).__name__ of a JSON value. */
export function pyType(v: unknown): string {
  if (v === null || v === undefined) return 'NoneType'
  if (typeof v === 'boolean') return 'bool'
  if (typeof v === 'number') return 'int'
  if (v instanceof PyFloat) return 'float'
  if (typeof v === 'string') return 'str'
  if (Array.isArray(v)) return 'list'
  return 'dict'
}

/** Python's truthiness of a JSON value. */
export function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === '') return false
  if (v instanceof PyFloat) return v.value !== 0
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return true
}

/** Python's '%0Nx': an integer in hex, zero-padded to `width` (a negative one keeps its sign inside the width). */
export const hexw = (n: number, width = 8): string =>
  (n < 0 ? '-' + (-n).toString(16).padStart(width - 1, '0') : n.toString(16).padStart(width, '0'))

/** '0x%08x'. */
export const hex8 = (n: number): string => '0x' + hexw(n, 8)

/** Python's repr() of a JSON value (and of the tuples and lists built from them). */
export function repr(v: unknown): string {
  if (v === null || v === undefined) return 'None'
  if (v === true) return 'True'
  if (v === false) return 'False'
  if (typeof v === 'number') return numRepr(v)
  if (v instanceof PyFloat) return floatRepr(v.value)
  if (typeof v === 'string') return strRepr(v)
  if (v instanceof Map) return '{' + [...v].map(([k, x]) => repr(k) + ': ' + repr(x)).join(', ') + '}'
  if (Array.isArray(v)) return '[' + v.map(repr).join(', ') + ']'
  if (typeof v === 'object') return '{' + Object.entries(v as object).map(([k, x]) => repr(k) + ': ' + repr(x)).join(', ') + '}'
  return String(v)
}

/** A tuple's repr: (a, b), or (a,) for one. */
export const tupleRepr = (items: unknown[]): string => '(' + items.map(repr).join(', ') + (items.length === 1 ? ',)' : ')')

/** Python's str(): repr() but for strings. */
export const str = (v: unknown): string => (typeof v === 'string' ? v : repr(v))

/** An int (a JSON integer: exact below 2**53). */
function numRepr(n: number): string {
  return Number.isInteger(n) ? BigInt(n).toString() : floatRepr(n)
}

/** Python's repr() of a float: the shortest digits that round-trip (as JavaScript's), positional for exponents
 * -4 to 15 with a '.0' on whole numbers, else d.ddde+XX with at least two exponent digits. */
export function floatRepr(n: number): string {
  if (Number.isNaN(n)) return 'nan'
  if (!Number.isFinite(n)) return n > 0 ? 'inf' : '-inf'
  if (n === 0) return Object.is(n, -0) ? '-0.0' : '0.0'
  const [mant, exp] = n.toExponential().split('e')
  const e = Number(exp)
  const sign = mant.startsWith('-') ? '-' : ''
  const digits = mant.replace(/^-/, '').replace('.', '')
  if (e >= -4 && e < 16) {
    let s: string
    if (e < 0) s = '0.' + '0'.repeat(-e - 1) + digits
    else if (digits.length > e + 1) s = digits.slice(0, e + 1) + '.' + digits.slice(e + 1)
    else s = digits + '0'.repeat(e + 1 - digits.length) + '.0'
    return sign + s
  }
  const m = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits
  return sign + m + 'e' + (e < 0 ? '-' : '+') + String(Math.abs(e)).padStart(2, '0')
}

function strRepr(s: string): string {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'"
  let out = q
  for (const ch of s) {
    const c = ch.codePointAt(0)!
    if (ch === q || ch === '\\') out += '\\' + ch
    else if (ch === '\n') out += '\\n'
    else if (ch === '\r') out += '\\r'
    else if (ch === '\t') out += '\\t'
    else if (c < 0x20 || c === 0x7f) out += '\\x' + hexw(c, 2)
    else out += ch
  }
  return out + q
}

/** Python's int(v, 0) as elemod._int uses it: an int stays one (a bool counts as 0 or 1); a string must be a
 * Python integer literal (0x/0o/0b, underscores between digits, no leading zeros). null otherwise. */
export function pyInt(v: unknown): number | null {
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'number') return Number.isInteger(v) ? v : null
  if (typeof v !== 'string') return null
  // Python reads any Unicode decimal digit as its value ('٣' is 3): each run of them counts 0 to 9
  const text = v.replace(/\p{Nd}/gu, ch => {
    const cp = ch.codePointAt(0)!
    if (cp < 0x80) return ch
    let start = cp
    while (/\p{Nd}/u.test(String.fromCodePoint(start - 1))) start--
    return String((cp - start) % 10)
  })
  const m = /^\s*([+-]?)(0[xX](?:_?[0-9a-fA-F])+|0[oO](?:_?[0-7])+|0[bB](?:_?[01])+|0(?:_?0)*|[1-9](?:_?[0-9])*)\s*$/.exec(text)
  if (!m) return null
  const body = m[2].replace(/_/g, '')
  const lower = body.toLowerCase()
  const n = lower.startsWith('0x') ? parseInt(body.slice(2), 16)
    : lower.startsWith('0o') ? parseInt(body.slice(2), 8)
      : lower.startsWith('0b') ? parseInt(body.slice(2), 2)
        : parseInt(body, 10)
  return m[1] === '-' ? -n : n
}

/** A JSON value whose object keys keep the order they were set in, numeric ones too (a Map), as a Python dict does. */
export type Json = null | boolean | number | string | Json[] | { [k: string]: Json } | Map<string, Json>

/** Python's json.dumps(value, indent=...), byte for byte for the values elekloader writes: ensure_ascii, the
 * ', ' and ': ' separators (',' between items once indented), and dicts in their own order. */
export function dumps(v: unknown, indent?: number): string {
  const nl = indent === undefined ? '' : '\n'
  const sep = indent === undefined ? ', ' : ','
  const pad = (level: number) => (indent === undefined ? '' : ' '.repeat(indent * level))
  const walk = (x: unknown, level: number): string => {
    if (x === null || x === undefined) return 'null'
    if (x === true) return 'true'
    if (x === false) return 'false'
    if (typeof x === 'number') return jsonNum(x)
    if (x instanceof PyFloat) return Number.isFinite(x.value) ? floatRepr(x.value) : jsonNum(x.value)
    if (typeof x === 'string') return jsonStr(x)
    const entries: [string, unknown][] | null = x instanceof Map ? [...x].map(([k, y]) => [String(k), y])
      : Array.isArray(x) ? null : Object.entries(x as object)
    if (entries === null) {
      const a = x as unknown[]
      if (!a.length) return '[]'
      return '[' + nl + a.map(y => pad(level + 1) + walk(y, level + 1)).join(sep + nl) + nl + pad(level) + ']'
    }
    if (!entries.length) return '{}'
    return '{' + nl + entries.map(([k, y]) => pad(level + 1) + jsonStr(k) + ': ' + walk(y, level + 1)).join(sep + nl)
      + nl + pad(level) + '}'
  }
  return walk(v, 0)
}

function jsonNum(n: number): string {
  if (Number.isInteger(n)) return BigInt(n).toString()
  if (Number.isNaN(n)) return 'NaN'
  if (!Number.isFinite(n)) return n > 0 ? 'Infinity' : '-Infinity'
  return floatRepr(n)
}

function jsonStr(s: string): string {
  let out = '"'
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i), ch = s[i]
    if (ch === '"') out += '\\"'
    else if (ch === '\\') out += '\\\\'
    else if (ch === '\n') out += '\\n'
    else if (ch === '\r') out += '\\r'
    else if (ch === '\t') out += '\\t'
    else if (ch === '\b') out += '\\b'
    else if (ch === '\f') out += '\\f'
    else if (c < 0x20 || c > 0x7e) out += '\\u' + hexw(c, 4)      // UTF-16 units: surrogate pairs stay pairs
    else out += ch
  }
  return out + '"'
}
