// SPDX-License-Identifier: GPL-3.0-or-later
// Device profiles: everything elekloader knows about one Elektron product. Ported from elekloader's devices/
// (GPL-2.0-or-later), whose files keep the evidence for each fact; the values here are theirs, unchanged.
import { str } from './py.ts'

export class UnknownFirmware extends Error {}

export type Release = {
  version: string        // the OS version, as Elektron names it
  syxSha256: string      // the stock .syx file
  mainSha256: string     // its main OS section, depacked
  mainLen: number        // ... and that section's length
  binSha256: string      // the stock card file (.bin), where the device has one
}

export type Range = [number, number]

export type Device = {
  key: string
  name: string
  sysexId: number
  releases: Release[]                           // in the profile's order
  mainSection: number
  mainLoad: number
  stage: number | null                          // null: unknown, so the in-place unpack is not simulated
  flashAt: number
  flashLimit: number
  trailer: null | 'hmac'
  isa: 'coldfire'
  hmacKeyFrom: [number, string] | null          // for 'hmac': the section and seed the key is derived from
  container: 'ele3' | 'elek'
  versionLen: number
  protected: [number, number, string][]        // main OS bytes no mod may change
  relocatable: [number, number, number[], string][]
  blobMax: number | null
  areas: Record<string, Range>                  // in the profile's order
  ddr: Range
  sramCode: Range
  fastTable: string
  imageFree: Range[]
  recovery: string
}

const rel = (version: string, syxSha256: string, mainSha256: string, mainLen: number, binSha256 = ''): Release =>
  ({ version, syxSha256, mainSha256, mainLen, binSha256 })

const base = {
  mainSection: 3, mainLoad: 0x40000400, isa: 'coldfire' as const, hmacKeyFrom: null, container: 'ele3' as const,
  versionLen: 4, protected: [], relocatable: [], blobMax: null, sramCode: [0, 0] as Range, fastTable: '',
  imageFree: [], trailer: null,
}

export const DIGITAKT_MK1: Device = {
  ...base,
  key: 'digitakt-mk1', name: 'Digitakt mk1', sysexId: 0x0a,
  releases: [
    rel('1.53', '9bdd44bb6102fb25c143cfab97bc92b7a89c463f795d3112dce89771e29bcc92',
      '4b47a9507758ca5669ca02ab2c0374d2c04c98aece445408295cc1dcb265c5df', 2475584),
    rel('1.54', 'f78ba80fa7b1da5fb0e1ff61ad61e9e71aafe79f4364fc49679f3651353e3cf6',
      '5c58bf9e3949ef09977c5fc007a61e8d026931f67f1621238379dfb8ee4d31a2', 2479680),
  ],
  stage: 0x40200000, flashAt: 0x80000, flashLimit: 0x380000,
  areas: { ddr: [0x47be0000, 0x47c00000], 'sram-tail': [0x8000f700, 0x80010000], 'sram-block': [0x80003360, 0x80008000] },
  ddr: [0x47be0000, 0x47c00000], sramCode: [0x8000f700, 0x80010000], fastTable: 'fa_copies',
  recovery: 'hold FUNC while powering on for the startup menu, then send the stock .syx',
}

export const DIGITAKT_MK2: Device = {
  ...base,
  key: 'digitakt-mk2', name: 'Digitakt II', sysexId: 0x14,
  releases: [
    rel('1.17', '26c22f6652625ac2cfd47f7ee970d388ed8b6427dae3563c0a6a2f2d334350d5',
      'a1e7b657b705eba1a19d81c33c1e11ba9c409816447ad74005d7bbf36da6d964', 3275616),
  ],
  stage: 0x40400000, flashAt: 0x80000, flashLimit: 0x380000, trailer: 'hmac', hmacKeyFrom: [2, 'Master Overdrive'],
  areas: { ddr: [0x47f00000, 0x47f40000], 'sram-tail': [0x8000f100, 0x80010000], 'sram-block': [0x80006e80, 0x80008000] },
  ddr: [0x47f00000, 0x47f40000], sramCode: [0x8000f100, 0x80010000], fastTable: 'core_fast',
  recovery: 'hold FUNC while powering on for the STARTUP menu, press TRIG 4 (OS UPGRADE), '
    + 'then send the stock .syx over MIDI (not USB)',
}

export const DIGITONE_MK1: Device = {
  ...base,
  key: 'digitone-mk1', name: 'Digitone mk1', sysexId: 0x0d,
  releases: [
    rel('1.43', 'c5a54cc05b921f2e4bd814834c5365c2a5aa01d7772a9a2961fac1c3095bf9aa',
      '3831a477a2a22befb23c42e47e782853da49566ef5d0a1767fcf6c30e6767414', 2732208),
    rel('1.44', 'd4f200d04484333d82822db7744e6484d0def8f2db8ddf55ee2b780cc13c9659',
      'fce648a97c6c5d93b961732e8f8db6b02e0820c6d344c7e2131fa05a4b3168e4', 2736304),
  ],
  stage: 0x40200000, flashAt: 0x80000, flashLimit: 0x380000,
  areas: { ddr: [0x47be0000, 0x47c00000] },
  ddr: [0x47be0000, 0x47c00000],
  recovery: 'hold FUNC while powering on for the startup menu, press TRIG 4 (OS UPGRADE), then send the stock .syx',
}

export const OCTATRACK: Device = {
  ...base,
  key: 'octatrack', name: 'Octatrack', sysexId: 0x05,
  releases: [
    rel('1.40C', '0a8d2d2b35c2cc78fa338576adc1af0cbc094cef973255103165c73edd87f2b6',
      '164f31224bf61181e3f50e7dec40df9afcae5b16dbf6e4c0d0cc5e986af0a84e', 1112560,
      '34695b606eb00e1b4dded5fd0c4b66f3a460522a632e47d7416dbd220599e1ad'),
  ],
  stage: null, flashAt: 0x4000, flashLimit: 0x200000, container: 'elek', versionLen: 10,
  protected: [[0x400de1e0, 0x400e21e0, 'the copy of the bootloader the OS can re-flash it from']],
  relocatable: [[0x400e2000, 18, [0x4001d82e], 'the USB device descriptor']],
  areas: { ddr: [0x40a955e0, 0x41495de0] },
  ddr: [0x40a955e0, 0x41495de0],
  imageFree: [[0x400c45b0, 0x400c4702], [0x400d24d0, 0x400d2ce0], [0x400d64e0, 0x400d7c3c]],
  recovery: 'hold FUNC while powering on for the startup menu, press TRIG 3 (MIDI UPGRADE) and send the stock '
    + '.syx over 5-pin MIDI (not USB)',
}

const DEVICES: Device[] = [DIGITAKT_MK1, DIGITAKT_MK2, DIGITONE_MK1, OCTATRACK]

export const devices = (): Device[] => DEVICES

export function releaseFor(d: Device, syxSha256?: string, mainSha256?: string): Release | null {
  for (const r of d.releases) {
    if (syxSha256 && (syxSha256 === r.syxSha256 || syxSha256 === r.binSha256)) return r
    if (mainSha256 && r.mainSha256 === mainSha256) return r
  }
  return null
}

/** Whether format-2 mods (a core, the linker's areas) exist for it. */
export const linkable = (d: Device): boolean => d.ddr[1] > d.ddr[0]

/** Where an appended blob loads: the stock main OS's end. */
export const imageEnd = (d: Device, r: Release): number => d.mainLoad + r.mainLen

export const supported = (): string => DEVICES.flatMap(d => d.releases.map(r => `${d.name} ${r.version}`)).join(', ')

/** -> [Device, Release] for a stock file, by its hash. */
export function identify(syxSha256: string): [Device, Release] {
  for (const d of DEVICES) {
    const r = releaseFor(d, syxSha256)
    if (r) return [d, r]
  }
  throw new UnknownFirmware(`not a stock firmware elekloader knows (sha256 ${syxSha256}). Supported: ${supported()}`)
}

type Target = Record<string, unknown>

/** -> [Device, Release] a .elemod's "target" names. */
export function forTarget(target: unknown): [Device, Release] {
  if (!target || typeof target !== 'object' || Array.isArray(target)) throw new UnknownFirmware('no target')
  const t = target as Target
  const key = t.device
  for (const d of DEVICES) {
    if (key && d.key !== key) continue
    const r = releaseFor(d, typeof t.syx_sha256 === 'string' ? t.syx_sha256 : undefined)
    if (r && ('section3_sha256' in t ? t.section3_sha256 : r.mainSha256) === r.mainSha256
        && ('section3_len' in t ? t.section3_len : r.mainLen) === r.mainLen) return [d, r]
  }
  const s = (x: unknown) => (x === undefined ? '?' : str(x))
  throw new UnknownFirmware(`made for a firmware elekloader does not know (${s(t.product)} ${s(t.os)})`)
}

/** -> the "target" object a .elemod for this firmware carries. */
export const targetOf = (d: Device, r: Release) => ({
  device: d.key, product: d.name, os: r.version, syx_sha256: r.syxSha256, section3_sha256: r.mainSha256,
  section3_len: r.mainLen,
})
