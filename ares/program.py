# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""A linked program: sections, labels, source lines and code/data mapping."""

import bisect
import struct
from dataclasses import dataclass
from typing import Optional

from elftools.elf.constants import SH_FLAGS
from elftools.elf.elffile import ELFFile

INSTRUCTION_SIZE = 4


@dataclass(frozen=True)
class Section:
    name: str
    address: int
    size: int
    data: Optional[bytes]       # None for sections without contents (.bss)
    executable: bool
    writable: bool

    @property
    def end(self):
        return self.address + self.size


@dataclass(frozen=True)
class Label:
    name: str
    address: int
    section: str
    is_global: bool


def _mapping_kind(name):
    """'a', 'd' or 't' for the ARM mapping symbols $a, $d, $t (and $a.N ...)."""
    if len(name) >= 2 and name[0] == "$" and name[1] in "adt" and (
            len(name) == 2 or name[2] == "."):
        return name[1]
    return None


def is_self_branch(word):
    """True for an ARM B instruction whose target is itself (``B .``)."""
    return (word & 0x0FFFFFFF) == 0x0AFFFFFE and (word >> 28) != 0xF


def is_wait_hint(word):
    """True for the hint instructions WFE and YIELD (any condition)."""
    return word is not None and (word & 0x0FFFFFFF) in (0x0320F001, 0x0320F002) and (
        word >> 28) != 0xF


class Program:
    """Everything ARES needs from a linked ELF file, read once."""

    def __init__(self, elf_path):
        with open(elf_path, "rb") as f:
            elf = ELFFile(f)
            self.entry = elf.header["e_entry"]
            self.sections = self._read_sections(elf)
            index_names = {i: s.name for i, s in enumerate(elf.iter_sections())}
            self.labels, mapping = self._read_symbols(elf, index_names)
            self.lines = self._read_lines(elf)
        self._code_runs = self._build_code_runs(mapping)
        self._line_addresses = sorted(self.lines)
        self.end_address = self._find_end_address()
        self.self_branches = self._find_self_branches()
        self.wait_hints = self._find_wait_hints()

    # Reading ------------------------------------------------------------

    @staticmethod
    def _read_sections(elf):
        sections = []
        for s in elf.iter_sections():
            flags = s["sh_flags"]
            if not flags & SH_FLAGS.SHF_ALLOC or s["sh_size"] == 0:
                continue
            data = None if s["sh_type"] == "SHT_NOBITS" else s.data()
            sections.append(Section(s.name, s["sh_addr"], s["sh_size"], data,
                                    bool(flags & SH_FLAGS.SHF_EXECINSTR),
                                    bool(flags & SH_FLAGS.SHF_WRITE)))
        sections.sort(key=lambda s: s.address)
        return sections

    @staticmethod
    def _read_symbols(elf, index_names):
        labels = []
        mapping = []        # (address, kind, section name)
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            return labels, mapping
        for sym in symtab.iter_symbols():
            shndx = sym["st_shndx"]
            if not isinstance(shndx, int) or not sym.name:
                continue        # undefined, absolute (.equ) or common symbols
            if sym["st_info"]["type"] in ("STT_SECTION", "STT_FILE"):
                continue
            section = index_names.get(shndx, "")
            kind = _mapping_kind(sym.name)
            if kind:
                mapping.append((sym["st_value"], kind, section))
            else:
                labels.append(Label(sym.name, sym["st_value"], section,
                                    sym["st_info"]["bind"] == "STB_GLOBAL"))
        labels.sort(key=lambda l: (l.address, l.name))
        return labels, mapping

    @staticmethod
    def _read_lines(elf):
        """Map each address with a line-table row to its source line."""
        lines = {}
        if not elf.has_dwarf_info():
            return lines
        dwarf = elf.get_dwarf_info()
        for cu in dwarf.iter_CUs():
            program = dwarf.line_program_for_CU(cu)
            if program is None:
                continue
            for entry in program.get_entries():
                state = entry.state
                if state is not None and not state.end_sequence:
                    lines.setdefault(state.address, state.line)
        return lines

    def _build_code_runs(self, mapping):
        """Per executable section: sorted (starts, ends) of its runs of instructions.

        A run is the part of an $a region that holds whole words on the
        section's 4-byte grid. An $a region that starts off the grid (code
        after a .hword) is not code: the CPU never fetches it as written.
        """
        runs = {}
        for section in self.sections:
            if not section.executable:
                continue
            marks = sorted((addr, kind) for addr, kind, name in mapping
                           if name == section.name)
            if not marks or marks[0][0] > section.address:
                marks.insert(0, (section.address, "a"))
            limits = [a for a, _ in marks[1:]] + [section.end]
            starts, ends = [], []
            for (start, kind), limit in zip(marks, limits):
                if kind != "a" or (start - section.address) % INSTRUCTION_SIZE:
                    continue
                end = start + (limit - start) // INSTRUCTION_SIZE * INSTRUCTION_SIZE
                if start < end:
                    starts.append(start)
                    ends.append(end)
            runs[section.name] = (starts, ends)
        return runs

    # Queries ------------------------------------------------------------

    def section_at(self, address):
        for section in self.sections:
            if section.address <= address < section.end:
                return section
        return None

    def is_code(self, address):
        """True when address starts an ARM instruction (not data or a literal pool)."""
        section = self.section_at(address)
        if section is None or not section.executable:
            return False
        if (address - section.address) % INSTRUCTION_SIZE:
            return False
        starts, ends = self._code_runs[section.name]
        i = bisect.bisect_right(starts, address) - 1
        return i >= 0 and address < ends[i]

    def code_runs(self, section):
        """(start, end) of each run of instructions in an executable section."""
        return list(zip(*self._code_runs[section.name]))

    def line_at(self, address):
        """Source line of the instruction at address, or None."""
        return self.lines.get(address)

    def read_word(self, address):
        section = self.section_at(address)
        if section is None or section.data is None:
            return None
        offset = address - section.address
        if offset + 4 > len(section.data):
            return None
        return struct.unpack_from("<I", section.data, offset)[0]

    def code_addresses(self):
        """Addresses of all instructions, in order."""
        for section in self.sections:
            if section.executable and section.data is not None:
                for start, end in self.code_runs(section):
                    yield from range(start, end, INSTRUCTION_SIZE)

    def label_address(self, name):
        for label in self.labels:
            if label.name == name:
                return label.address
        return None

    def text_rows(self, source_text, tab_size=4):
        """Rows of the Text Segment table (see ares.disasm.text_rows)."""
        from .disasm import text_rows       # loads Capstone only when a table is needed
        return text_rows(self, source_text, tab_size)

    # Program-end rules --------------------------------------------------

    def _find_end_address(self):
        """Address after the last instruction that has a source line."""
        code_lines = [a for a in self._line_addresses if self.is_code(a)]
        return code_lines[-1] + INSTRUCTION_SIZE if code_lines else None

    def _find_self_branches(self):
        """(address, condition) of every instruction that branches to itself."""
        found = []
        for address in self.code_addresses():
            word = self.read_word(address)
            if word is not None and is_self_branch(word):
                found.append((address, word >> 28))
        return found

    def _find_wait_hints(self):
        """Addresses of WFE and YIELD, which the CPU emulator cannot execute."""
        return [address for address in self.code_addresses()
                if is_wait_hint(self.read_word(address))]
