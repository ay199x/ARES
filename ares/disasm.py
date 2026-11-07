# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Text Segment rows: the executable sections disassembled for display."""

import re
import struct
import unicodedata
from dataclasses import dataclass
from typing import Optional

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_OPT_SYNTAX_NOREGNAME, Cs

from .program import INSTRUCTION_SIZE

TAB_SIZE = 4                # columns per tab when the Source column shows a line

_disassembler = Cs(CS_ARCH_ARM, CS_MODE_ARM)
_disassembler.syntax = CS_OPT_SYNTAX_NOREGNAME     # R9-R12, not SB, SL, FP, IP

_HEX_PREFIX = re.compile(r"\b0X")


@dataclass(frozen=True)
class TextRow:
    """One row of the Text Segment table: a word of an executable section."""
    address: int
    code: int               # the word (fewer bytes in a short last row)
    basic: str
    line: Optional[int]     # source line of the instruction at this row, if any
    source: str             # "N: text" with N aligned, or "" without a source line of its own


def format_address(address):
    """'0x' and 8 lowercase hex digits, as in the Address and Code columns."""
    return f"0x{address:08x}"


def data_word(word):
    return f".word 0x{word:08X}"


def _capitals(mnemonic, op_str):
    """Capitals everywhere except the '0x' of hexadecimal numbers."""
    return _HEX_PREFIX.sub("0x", f"{mnemonic} {op_str}".rstrip().upper())


def basic(word, address):
    """Basic-column text of one instruction word at address."""
    for _, _, mnemonic, op_str in _disassembler.disasm_lite(struct.pack("<I", word),
                                                            address, 1):
        return _capitals(mnemonic, op_str)
    return data_word(word)


def _disassemble(code, address):
    """Basic text of each word of code, which starts at address."""
    texts = []
    while len(texts) * INSTRUCTION_SIZE < len(code):
        offset = len(texts) * INSTRUCTION_SIZE
        for _, _, mnemonic, op_str in _disassembler.disasm_lite(code[offset:],
                                                                address + offset):
            texts.append(_capitals(mnemonic, op_str))
        offset = len(texts) * INSTRUCTION_SIZE
        if offset < len(code):              # Capstone stops at a word it cannot decode
            texts.append(data_word(int.from_bytes(code[offset:offset + INSTRUCTION_SIZE],
                                                  "little")))
    return texts


def _code_rows(program, code, address, source):
    rows = []
    texts = _disassemble(code, address)     # Capstone sees the whole run at once
    for (word,), text in zip(struct.iter_unpack("<I", code), texts):
        line = program.line_at(address)
        rows.append(TextRow(address, word, text, line, source(line)))
        address += INSTRUCTION_SIZE
    return rows


def _data_rows(data, address):
    """Literal pools and other data: no disassembly and no source line."""
    whole = len(data) - len(data) % INSTRUCTION_SIZE
    rows = [TextRow(address + offset, word, data_word(word), None, "")
            for offset, (word,) in zip(range(0, whole, INSTRUCTION_SIZE),
                                       struct.iter_unpack("<I", data[:whole]))]
    if whole < len(data):                   # an executable section holding only data
        tail = data[whole:]
        rows.append(TextRow(address + whole, int.from_bytes(tail, "little"),
                            ".byte " + ", ".join(f"0x{b:02X}" for b in tail), None, ""))
    return rows


def _section_rows(program, section, source):
    """The rows of an executable section, and for each whether it is an instruction."""
    base, data = section.address, section.data
    rows, instructions = [], []
    position = base
    for start, end in program.code_runs(section) + [(section.end, section.end)]:
        part = _data_rows(data[position - base:start - base], position)
        rows += part
        instructions += [False] * len(part)
        part = _code_rows(program, data[start - base:end - base], start, source)
        rows += part
        instructions += [True] * len(part)
        position = end
    return rows, instructions


class SourceColumn:
    """The Source column's text for each source line: its number, then the line as written.

    The numbers are right-aligned to the widest one with an instruction, so
    the lines start in one column.
    """

    def __init__(self, program, source_text):
        self.lines = source_text.split("\n") if source_text else []
        shown = [line for address, line in program.lines.items()
                 if 1 <= line <= len(self.lines) and program.is_code(address)]
        self.digits = len(str(max(shown, default=0)))

    def text(self, line, tab_size=TAB_SIZE):
        """The text for line number line, tabs expanded; "" for None or a line not in the source."""
        if line is None or not 1 <= line <= len(self.lines):
            return ""
        return f"{line:>{self.digits}}: {self.lines[line - 1].expandtabs(tab_size).rstrip()}"


def text_columns(text):
    """Character cells text takes in a fixed-width font: wide East Asian characters take two."""
    if text.isascii():
        return len(text)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


@dataclass(frozen=True)
class Listing:
    """A program's Text Segment rows, with what the table needs to show them.

    listing() makes it while assembling, away from the window, so a large
    code section does not hold the window up.
    """
    rows: list              # TextRow, in address order
    instructions: list      # for each row, whether it is an instruction (program.is_code)
    sources: SourceColumn   # makes the Source texts again for another tab width
    tab_size: int           # the tab width of the rows' Source texts
    widest_basic: int       # character cells of the widest Basic text
    widest_source: int      # character cells of the widest Source text


def listing(program, source_text, tab_size=TAB_SIZE):
    """The Text Segment rows of a program (see text_rows), with what the table needs."""
    sources = SourceColumn(program, source_text)
    rows, instructions = [], []
    for section in program.sections:
        if section.executable and section.data is not None:
            part, kinds = _section_rows(program, section,
                                        lambda line: sources.text(line, tab_size))
            rows += part
            instructions += kinds
    return Listing(rows, instructions, sources, tab_size,
                   max((len(row.basic) for row in rows), default=0),
                   max((text_columns(row.source) for row in rows), default=0))


def text_rows(program, source_text, tab_size=TAB_SIZE):
    """Text Segment rows for every word of every executable section, in address order.

    Instructions are disassembled and show their source line as written
    (tabs expanded to tab_size columns) after its number; the numbers are
    right-aligned, so the lines start in one column. Literal pools and other
    data are shown as ``.word`` (``.byte`` for a last part shorter than a
    word) with no source line; ``program.is_code`` tells the two apart.
    """
    return listing(program, source_text, tab_size).rows
