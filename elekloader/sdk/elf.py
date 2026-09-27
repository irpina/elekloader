# SPDX-License-Identifier: GPL-2.0-or-later
"""A reader for 32-bit big-endian ELF relocatable objects (m68k): sections,
symbols and RELA relocations, as sdk/build.py needs them."""
import struct

SHT_SYMTAB, SHT_RELA, SHT_NOBITS, SHT_REL = 2, 4, 8, 9
SHN_UNDEF, SHN_ABS, SHN_COMMON = 0, 0xFFF1, 0xFFF2
STB_LOCAL, STB_GLOBAL, STB_WEAK = 0, 1, 2
STT_NOTYPE, STT_OBJECT, STT_FUNC, STT_SECTION, STT_FILE = 0, 1, 2, 3, 4
# m68k relocation types
R_68K_NONE, R_68K_32, R_68K_16, R_68K_8, R_68K_PC32, R_68K_PC16, R_68K_PC8 = range(7)
RNAMES = {R_68K_32: 'abs32', R_68K_PC32: 'pc32', R_68K_PC16: 'pc16', R_68K_16: 'abs16',
          R_68K_8: 'abs8', R_68K_PC8: 'pc8'}


class Section:
    def __init__(self, idx, name, typ, flags, offset, size, link, info, align, data):
        self.idx, self.name, self.type, self.flags = idx, name, typ, flags
        self.offset, self.size, self.link, self.info, self.align = offset, size, link, info, align
        self.data = data


class Symbol:
    def __init__(self, idx, name, value, size, bind, typ, shndx):
        self.idx, self.name, self.value, self.size = idx, name, value, size
        self.bind, self.type, self.shndx = bind, typ, shndx


class Elf:
    def __init__(self, raw):
        if raw[:4] != b'\x7fELF' or raw[4] != 1 or raw[5] != 2:
            raise ValueError('not a 32-bit big-endian ELF')
        self.raw = raw
        self.etype, = struct.unpack_from('>H', raw, 16)
        shoff, = struct.unpack_from('>I', raw, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from('>HHH', raw, 0x2E)
        hdrs = [struct.unpack_from('>IIIIIIIIII', raw, shoff + i * shentsize) for i in range(shnum)]
        strtab = hdrs[shstrndx]
        names = raw[strtab[4]:strtab[4] + strtab[5]]

        def cstr(buf, o):
            return buf[o:buf.index(b'\0', o)].decode('ascii', 'replace')
        self.sections = []
        for i, h in enumerate(hdrs):
            name, typ, flags, _addr, off, size, link, info, align, _ent = h
            data = b'' if typ == SHT_NOBITS else raw[off:off + size]
            self.sections.append(Section(i, cstr(names, name), typ, flags, off, size, link,
                                         info, align, data))
        self.symbols = []
        symtab = [s for s in self.sections if s.type == SHT_SYMTAB]
        if symtab:
            st = symtab[0]
            strs = self.sections[st.link].data
            for k in range(st.size // 16):
                n, value, size, info, _other, shndx = struct.unpack_from('>IIIBBH', st.data, 16 * k)
                self.symbols.append(Symbol(k, cstr(strs, n) if n else '', value, size,
                                           info >> 4, info & 15, shndx))
        self.relocs = {}                   # target section index -> [(offset, type, sym, addend)]
        for s in self.sections:
            if s.type == SHT_REL:
                raise ValueError('REL relocations (%s): expected RELA' % s.name)
            if s.type != SHT_RELA:
                continue
            out = self.relocs.setdefault(s.info, [])
            for k in range(s.size // 12):
                off, info, addend = struct.unpack_from('>IIi', s.data, 12 * k)
                out.append((off, info & 0xFF, self.symbols[info >> 8], addend))

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as fh:
            return cls(fh.read())

    def section(self, name):
        for s in self.sections:
            if s.name == name:
                return s
        return None
