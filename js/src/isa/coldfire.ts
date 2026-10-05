// SPDX-License-Identifier: GPL-3.0-or-later
// ColdFire ISA_C + EMAC instruction lengths, flags and control flow, enough for patch-site boundary checks.
// From modwerk (https://github.com/repeat98/modwerk, src/engine/elektron/coldfire-isa.ts, by repeat98,
// GPL-3.0-or-later), which ported it from the decoder in digikit / elekloader (emu/cfisa.py, isa/coldfire.py;
// GPL-2.0-or-later, by irpina), following the ColdFire Family Programmer's Reference Manual's encodings. Changed
// here to match isa/coldfire.py exactly, as the linker's messages name the op: its op names (bitrev, byterev,
// ff1, bchgi), and only a bad encoding (not a read past the image) shortens an FPU instruction. Reads no firmware.

export const FPU = 1, LINEF = 2, ILLEGAL = 4, PRIV = 8, MOVEC = 16, EMAC_OP = 32, PCREL = 64
export type Flow = 'none' | 'bcc' | 'bra' | 'bsr' | 'jmp' | 'jsr' | 'rts' | 'rte' | 'trap'
export type Instruction = { length: number; op: string; flags: number; flow: Flow; target?: number }
export type Read16 = (offset: number) => number

class Bad extends Error {}
const s16 = (v: number) => (v & 0x8000 ? v - 0x10000 : v)
const s8 = (v: number) => (v & 0x80 ? v - 0x100 : v)
const s32 = (v: number) => (v & 0x80000000 ? v - 0x100000000 : v)
const u32 = (v: number) => ((v % 0x100000000) + 0x100000000) % 0x100000000
const insn = (length: number, op: string, flags = 0, flow: Flow = 'none', target?: number): Instruction => ({ length, op, flags, flow, ...(target === undefined ? {} : { target }) })

/** One effective address -> [extension bytes, flags]. `pos` is the byte offset of its first extension word. */
function ea(mode: number, reg: number, size: number, read16: Read16, pos: number): [number, number, boolean] {
  if (mode <= 4) return [0, 0, mode <= 1]
  if (mode === 5) return [2, 0, false]
  if (mode === 6) { if (read16(pos) & 0x0100) throw new Bad('full-format extension word'); return [2, 0, false] }
  if (reg === 0) return [2, 0, false]
  if (reg === 1) return [4, 0, false]
  if (reg === 2) return [2, PCREL, false]
  if (reg === 3) { if (read16(pos) & 0x0100) throw new Bad('full-format extension word'); return [2, PCREL, false] }
  if (reg === 4) { if (size <= 0) throw new Bad('immediate not allowed here'); return [size === 4 ? 4 : 2, 0, false] }
  throw new Bad('mode 7 register ' + reg)
}

function one(op: string, w: number, read16: Read16, size: number, options: { alt?: boolean; immOk?: boolean; extraWords?: number; flags?: number } = {}): Instruction {
  const mode = (w >> 3) & 7, reg = w & 7, extraWords = options.extraWords ?? 0
  if (mode === 1 && options.alt) throw new Bad('An not allowed')
  const [ext, flags] = ea(mode, reg, options.immOk === false ? 0 : size, read16, 2 + 2 * extraWords)
  return insn(2 + 2 * extraWords + ext, op, (options.flags ?? 0) | flags)
}

/** The instruction at `addr`. Never throws: opcodes outside ISA_C/EMAC decode as length 2 with ILLEGAL, FPU or LINEF. */
export function decodeColdFire(read16: Read16, addr = 0): Instruction {
  try { return decode(read16, addr) } catch (error) {
    if (!(error instanceof Bad) && !(error instanceof RangeError)) throw error
    const w = read16(0)
    if (w >> 12 === 0xf) return insn(2, 'linef', (w & 0xfe00) === 0xf200 || (w & 0xff80) === 0xf300 ? FPU : LINEF)
    return insn(2, 'illegal', ILLEGAL)
  }
}

function decode(read16: Read16, addr: number): Instruction {
  const w = read16(0), line = w >> 12, mode = (w >> 3) & 7, reg = w & 7
  if (line === 0) {
    const hi = w & 0xfff8
    if ([0x0080, 0x0280, 0x0480, 0x0680, 0x0a80, 0x0c80].includes(hi)) return insn(6, hi === 0x0c80 ? 'cmpi' : 'alu_imm')
    if (hi === 0x0c00 || hi === 0x0c40) return insn(4, 'cmpi')
    if (hi === 0x00c0) return insn(2, 'bitrev')
    if (hi === 0x02c0) return insn(2, 'byterev')
    if (hi === 0x04c0) return insn(2, 'ff1')
    if ((w & 0xf100) === 0x0100) {
      const kind = (w >> 6) & 3
      if (mode === 1) throw new Bad('bit op on An')
      return one(kind === 0 ? 'btst' : 'bchg', w, read16, mode === 0 ? 4 : 1, { immOk: kind === 0 })
    }
    if ((w & 0xff00) === 0x0800) {
      const kind = (w >> 6) & 3
      if (mode === 1 || (mode === 7 && reg >= 2)) throw new Bad('static bit op EA')
      return one(kind === 0 ? 'btsti' : 'bchgi', w, read16, mode === 0 ? 4 : 1, { extraWords: 1 })
    }
    throw new Bad('line 0')
  }
  if (line >= 1 && line <= 3) {
    const size = line === 1 ? 1 : line === 2 ? 4 : 2, dmode = (w >> 6) & 7, dreg = (w >> 9) & 7
    if (dmode === 1 && size === 1) throw new Bad('movea.b')
    const [sext, sflags] = ea(mode, reg, size, read16, 2)
    if (dmode === 7 && dreg >= 2) throw new Bad('move destination')
    const [dext, dflags] = ea(dmode, dreg, 0, read16, 2 + sext)
    return insn(2 + sext + dext, dmode === 1 ? 'movea' : 'move', sflags | dflags)
  }
  if (line === 4) return line4(w, read16, addr, mode, reg)
  if (line === 5) {
    if (w === 0x51fa) return insn(4, 'tpf')
    if (w === 0x51fb) return insn(6, 'tpf')
    if (w === 0x51fc) return insn(2, 'tpf')
    if ((w & 0xf1c0) === 0x5080 || (w & 0xf1c0) === 0x5180) { if (mode === 7 && reg >= 2) throw new Bad('addq EA'); return one('addq', w, read16, 4) }
    if ((w & 0xf0f8) === 0x50c0) return insn(2, 'scc')
    throw new Bad('line 5')
  }
  if (line === 6) {
    const cond = (w >> 8) & 15, d8 = w & 0xff
    const [length, displacement] = d8 === 0 ? [4, s16(read16(2))] : d8 === 0xff ? [6, s32(((read16(2) << 16) | read16(4)) >>> 0)] : [2, s8(d8)]
    const flow: Flow = cond === 0 ? 'bra' : cond === 1 ? 'bsr' : 'bcc'
    return insn(length, flow, 0, flow, u32(addr + 2 + displacement))
  }
  if (line === 7) {
    if (!(w & 0x0100)) return insn(2, 'moveq')
    const ss = (w >> 6) & 3
    return one('mvsz', w, read16, ss === 0 || ss === 2 ? 1 : 2)
  }
  if (line === 0x8 || line === 0x9 || line === 0xc || line === 0xd) {
    const opmode = (w >> 6) & 7
    if (opmode === 2) { if (mode === 1 && (line === 0x8 || line === 0xc)) throw new Bad('and/or from An'); return one('alu_ea_r', w, read16, 4) }
    if (opmode === 6) {
      if ((line === 0x9 || line === 0xd) && mode === 0) return insn(2, 'addx')
      if (mode <= 1 || (mode === 7 && reg >= 2)) throw new Bad('op Dn,<ea> EA')
      return one('alu_r_ea', w, read16, 4)
    }
    if (opmode === 7 && (line === 0x9 || line === 0xd)) return one('alu_ea_r', w, read16, 4)
    if ((opmode === 3 || opmode === 7) && (line === 0x8 || line === 0xc)) { if (mode === 1) throw new Bad('mul/div An'); return one(line === 0x8 ? 'div_w' : 'mul_w', w, read16, 2) }
    throw new Bad('line ' + line.toString(16) + ' opmode ' + opmode)
  }
  if (line === 0xa) return lineA(w, read16, mode, reg)
  if (line === 0xb) {
    const opmode = (w >> 6) & 7
    if (opmode <= 2) { const size = [1, 2, 4][opmode]; if (mode === 1 && size === 1) throw new Bad('cmp.b An'); return one('alu_ea_r', w, read16, size) }
    if (opmode === 3 || opmode === 7) return one('alu_ea_r', w, read16, opmode === 3 ? 2 : 4)
    if (opmode === 6) { if (mode === 1 || (mode === 7 && reg >= 2)) throw new Bad('eor EA'); return one('alu_r_ea', w, read16, 4) }
    throw new Bad('line B')
  }
  if (line === 0xe) { if ((w & 0xc0) !== 0x80 || (w & 0x10)) throw new Bad('shift form'); return insn(2, 'shift') }
  if (line === 0xf) {
    if ((w & 0xff38) === 0xf428) return insn(2, ((w >> 6) & 3) === 0 ? 'intouch' : 'cpushl', PRIV)
    if ((w & 0xffc0) === 0xfbc0) { if (read16(2) !== 0x0003) throw new Bad('wdebug'); return one('wdebug', w, read16, 4, { extraWords: 1, immOk: false, flags: PRIV }) }
    if ((w & 0xff00) === 0xfb00 && (w & 0xc0) !== 0xc0) return one('wddata', w, read16, [1, 2, 4][(w >> 6) & 3], { immOk: false })
    if ((w & 0xfe00) === 0xf200 || (w & 0xff80) === 0xf300) return insn(fpuLength(w, read16), 'fpu', FPU)
    return insn(2, 'linef', LINEF)
  }
  throw new Bad('line ' + line)
}

function line4(w: number, read16: Read16, addr: number, mode: number, reg: number): Instruction {
  if ((w & 0xf1c0) === 0x41c0) { if (mode === 0 || mode === 1 || mode === 3 || mode === 4 || (mode === 7 && reg === 4)) throw new Bad('lea EA'); return one('lea', w, read16, 4, { immOk: false }) }
  if (w === 0x40e7) { if (read16(2) !== 0x46fc) throw new Bad('stldsr'); return insn(6, 'stldsr', PRIV) }
  const hi = w & 0xfff8, top = w & 0xffc0
  if (hi === 0x4080) return insn(2, 'negx')
  if (hi === 0x40c0) return insn(2, 'move_from_sr', PRIV)
  if (top === 0x4200 || top === 0x4240 || top === 0x4280) { if (mode === 1) throw new Bad('clr An'); return one('clr', w, read16, top === 0x4200 ? 1 : top === 0x4240 ? 2 : 4, { immOk: false }) }
  if (hi === 0x42c0) return insn(2, 'move_from_ccr')
  if (hi === 0x4480) return insn(2, 'neg')
  if (top === 0x44c0) { if (mode !== 0 && !(mode === 7 && reg === 4)) throw new Bad('move to ccr EA'); return one('move_to_ccr', w, read16, 2) }
  if (hi === 0x4680) return insn(2, 'not')
  if (top === 0x46c0) { if (mode !== 0 && !(mode === 7 && reg === 4)) throw new Bad('move to sr EA'); return one('move_to_sr', w, read16, 2, { flags: PRIV }) }
  if (hi === 0x4840) return insn(2, 'swap')
  if (top === 0x4840) { if (mode === 0 || mode === 1 || mode === 3 || mode === 4 || (mode === 7 && reg === 4)) throw new Bad('pea EA'); return one('pea', w, read16, 4, { immOk: false }) }
  if (hi === 0x4880 || hi === 0x48c0) return insn(2, 'ext')
  if (top === 0x48c0 || top === 0x4cc0) { if (mode !== 2 && mode !== 5) throw new Bad('movem EA'); return one('movem', w, read16, 4, { extraWords: 1 }) }
  if (hi === 0x49c0) return insn(2, 'extb')
  if (w === 0x4ac8) return insn(2, 'halt', PRIV)
  if (w === 0x4acc) return insn(2, 'pulse')
  if (w === 0x4afc) return insn(2, 'illegal', ILLEGAL)
  if (top === 0x4a00 || top === 0x4a40 || top === 0x4a80) return one('tst', w, read16, top === 0x4a00 ? 1 : top === 0x4a40 ? 2 : 4)
  if (top === 0x4ac0) { if (mode <= 1 || (mode === 7 && reg >= 2)) throw new Bad('tas EA'); return one('tas', w, read16, 1) }
  if (top === 0x4c00) { if (mode === 1 || mode === 6 || (mode === 7 && [0, 1, 3].includes(reg))) throw new Bad('mul.l EA'); return one('mul_l', w, read16, 4, { extraWords: 1 }) }
  if (top === 0x4c40) { if (mode === 1 || mode === 6 || (mode === 7 && [0, 1, 3, 4].includes(reg))) throw new Bad('div.l EA'); return one('div_l', w, read16, 4, { extraWords: 1 }) }
  if (hi === 0x4c80) return insn(2, 'sats')
  if ((w & 0xfff0) === 0x4e40) return insn(2, 'trap', 0, 'trap')
  if (hi === 0x4e50) return insn(4, 'link')
  if (hi === 0x4e58) return insn(2, 'unlk')
  if (hi === 0x4e60 || hi === 0x4e68) return insn(2, 'move_usp', PRIV)
  if (w === 0x4e71) return insn(2, 'nop')
  if (w === 0x4e72) return insn(4, 'stop', PRIV)
  if (w === 0x4e73) return insn(2, 'rte', PRIV, 'rte')
  if (w === 0x4e75) return insn(2, 'rts', 0, 'rts')
  if (w === 0x4e7a || w === 0x4e7b) return insn(4, 'movec', PRIV | MOVEC)
  if (top === 0x4e80 || top === 0x4ec0) {
    if (mode === 0 || mode === 1 || mode === 3 || mode === 4 || (mode === 7 && reg === 4)) throw new Bad('jmp EA')
    const jsr = top === 0x4e80, base = one(jsr ? 'jsr' : 'jmp', w, read16, 4, { immOk: false })
    const target = mode === 7 && reg === 0 ? u32(s16(read16(2))) : mode === 7 && reg === 1 ? ((read16(2) << 16) | read16(4)) >>> 0 : mode === 7 && reg === 2 ? u32(addr + 2 + s16(read16(2))) : undefined
    return { ...base, flow: jsr ? 'jsr' : 'jmp', ...(target === undefined ? {} : { target }) }
  }
  throw new Bad('line 4')
}

function lineA(w: number, read16: Read16, mode: number, reg: number): Instruction {
  if ((w & 0xf1c0) === 0xa140) { if (mode === 7 && reg >= 2) throw new Bad('mov3q EA'); return one('mov3q', w, read16, 4) }
  if ((w & 0xffc0) === 0xad00) return one('to_mask', w, read16, 4)
  if ((w & 0xfbc0) === 0xab00) return one('to_accext', w, read16, 4)
  if ((w & 0xffc0) === 0xa900) return one('to_macsr', w, read16, 4)
  if ((w & 0xf9c0) === 0xa100) return one('to_acc', w, read16, 4, { flags: EMAC_OP })
  if (w === 0xa9c0) return insn(2, 'macsr_ccr')
  if ((w & 0xfbf0) === 0xab80 || (w & 0xfff0) === 0xad80 || (w & 0xfff0) === 0xa980) return insn(2, 'from_emac')
  if ((w & 0xf1fe) === 0xa110) return insn(2, 'acc_to_acc')
  if ((w & 0xf9b0) === 0xa180) return insn(2, 'from_acc')
  if ((w & 0xf100) === 0xa000) {
    if (w & 0x30) { if (mode < 2 || mode > 5) throw new Bad('mac load EA'); return one('mac', w, read16, 4, { extraWords: 1, flags: EMAC_OP }) }
    return insn(4, 'mac', EMAC_OP)
  }
  throw new Bad('line A')
}

const FP_SIZES: Record<number, number> = { 0: 4, 1: 4, 2: 12, 3: 12, 4: 2, 5: 8, 6: 1, 7: 12 }
function fpuLength(w: number, read16: Read16): number {
  if ((w & 0xff80) === 0xf280) return w & 0x40 ? 6 : 4
  if ((w & 0xff80) === 0xf300) {
    try { return 2 + ea((w >> 3) & 7, w & 7, 0, read16, 2)[0] } catch (e) { if (e instanceof Bad) return 2; throw e }
  }
  const ext = read16(2), mode = (w >> 3) & 7, reg = w & 7
  let size = ext & 0x4000 ? FP_SIZES[(ext >> 10) & 7] ?? 4 : 0
  if ([0x8000, 0xa000, 0xc000, 0xe000].includes(ext & 0xe000)) size = 4
  if (size && mode === 7 && reg === 4) return 4 + (size > 2 ? size : 2)
  try {
    return 4 + ((mode || reg) && (ext & 0x4000 || ext & 0x8000) ? ea(mode, reg, size || 4, read16, 4)[0] : 0)
  } catch (e) {
    if (e instanceof Bad) return 4
    throw e
  }
}

/** read16 for decodeColdFire over `data` loaded at `base`, for the instruction at `addr`. */
export function readerAt(data: Uint8Array, base: number) {
  return (addr: number): Read16 => (offset: number) => {
    const i = addr - base + offset
    if (i < 0 || i + 1 >= data.length) throw new RangeError('read outside the image')
    return (data[i] << 8) | data[i + 1]
  }
}

/**
 * Do [addr, addr+n) hold whole instructions? The end must be exact; the start is checked by `sweeps` linear
 * decodes started 32–94 bytes earlier, which must all land on it (the stream resynchronises within a few words).
 */
export function wholeInstructionsAt(image: Uint8Array, base: number, addr: number, n: number, sweeps = 32): { ok: boolean; note: string } {
  const read = readerAt(image, base), bad = ILLEGAL | LINEF | FPU
  let at = addr
  while (at < addr + n) {
    const instruction = decodeColdFire(read(at), at)
    if (instruction.flags & bad) return { ok: false, note: '0x' + at.toString(16).padStart(8, '0') + ' does not decode' }
    at += instruction.length
  }
  if (at !== addr + n) return { ok: false, note: 'ends mid-instruction (0x' + at.toString(16).padStart(8, '0') + ')' }
  let landed = 0, ran = 0
  for (let k = 16; k < 16 + sweeps; k++) {
    let pc = addr - 2 * k
    if (pc < base) break
    while (pc < addr) pc += decodeColdFire(read(pc), pc).length
    ran++
    if (pc === addr) landed++
  }
  return landed === ran ? { ok: true, note: 'whole instructions' } : { ok: false, note: 'only ' + landed + ' of ' + ran + ' sweeps land on the start' }
}
