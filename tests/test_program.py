# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Loading the linked ELF: sections, labels, line table, code/data mapping."""

from elftools.elf.elffile import ELFFile

from ares.assembler import assemble
from ares.program import Program, _mapping_kind, is_self_branch

SOURCE = """\
        .global _start
        .text
helper:
        BX      LR
_start:
        LDR     R0, =0x12345678
        BL      helper
        BEQ     .
        B       .

        .data
value:  .word   7
text:   .asciz  "hi"
        .bss
buffer: .space  16
"""
# Lines:  4 BX, 6 LDR, 7 BL, 8 BEQ, 9 B; literal pool after B.


def test_sections_are_contiguous_from_zero(build):
    program = build(SOURCE)
    names = [s.name for s in program.sections]
    assert names == [".text", ".data", ".bss"]
    text, data, bss = program.sections
    assert text.address == 0 and text.executable and not text.writable
    assert data.address == text.end and data.writable
    assert data.address % 4 == 0
    assert bss.address == (data.end + 3) & ~3
    assert bss.data is None and bss.size == 16


def test_labels(build):
    program = build(SOURCE)
    labels = {l.name: l for l in program.labels}
    assert set(labels) == {"helper", "_start", "value", "text", "buffer"}
    assert labels["helper"].address == 0 and not labels["helper"].is_global
    assert labels["_start"].address == 4 and labels["_start"].is_global
    assert labels["value"].section == ".data"
    assert program.label_address("_start") == 4
    assert program.label_address("nothing") is None
    assert [l.address for l in program.labels] == sorted(l.address for l in program.labels)


def test_line_table(build):
    program = build(SOURCE)
    assert [program.line_at(a) for a in range(0, 20, 4)] == [4, 6, 7, 8, 9]
    assert program.line_at(2) is None


def test_literal_pool_is_data(build):
    program = build(SOURCE)
    assert [program.is_code(a) for a in range(0, 24, 4)] == [True] * 5 + [False]
    assert program.read_word(20) == 0x12345678
    assert list(program.code_addresses()) == [0, 4, 8, 12, 16]


def test_end_address_skips_literal_pool(build):
    assert build(SOURCE).end_address == 20


def test_self_branches_found(build):
    assert build(SOURCE).self_branches == [(12, 0x0), (16, 0xE)]


def test_is_self_branch():
    assert is_self_branch(0xEAFFFFFE)       # B .
    assert is_self_branch(0x0AFFFFFE)       # BEQ .
    assert not is_self_branch(0xEBFFFFFE)   # BL .
    assert not is_self_branch(0xFAFFFFFE)   # BLX (immediate)
    assert not is_self_branch(0xEAFFFFFD)   # B to the previous instruction


LAYOUT = """\
        .global _start
        .text
_start: LDR     R0, =msg
        B       .
        .section .rodata
msg:    .asciz  "hey!"
        .section .vectors, "ax"
vec:    B       _start
        .ltorg
        .word   0x11223344
        .data
value:  .word   7
"""


def test_rodata_follows_text_and_precedes_data(build):
    program = build(LAYOUT.replace('        .section .vectors, "ax"\n', "        .text\n"))
    names = [s.name for s in program.sections]
    assert names == [".text", ".rodata", ".data"]
    text, rodata, data = program.sections
    assert rodata.address == (text.end + 3) & ~3
    assert not rodata.executable and not rodata.writable
    assert rodata.data == b"hey!\0"
    assert data.address == (rodata.end + 3) & ~3
    assert program.read_word(text.end - 8) == rodata.address     # =msg in the pool


def test_extra_code_section_is_placed_after_text(build):
    program = build(LAYOUT)
    names = [s.name for s in program.sections]
    assert names == [".text", ".vectors", ".rodata", ".data"]
    text, vectors, rodata, _ = program.sections
    assert vectors.address == (text.end + 3) & ~3
    assert vectors.executable and not vectors.writable
    assert rodata.address == (vectors.end + 3) & ~3
    assert program.is_code(vectors.address)
    assert not program.is_code(vectors.address + 4)
    assert program.read_word(vectors.address + 4) == 0x11223344


def test_code_runs(build):
    program = build(SOURCE)
    assert program.code_runs(program.sections[0]) == [(0, 20)]


def test_code_off_the_word_grid_is_data(build):
    # GNU as places B . after .hword at 6; the CPU never fetches it there.
    program = build("        .global _start\n_start: MOV R0, #1\n"
                    "        .hword 7\n        B .\n")
    assert program.line_at(6) == 4
    assert program.code_runs(program.sections[0]) == [(0, 4)]
    assert [program.is_code(a) for a in range(0, 12, 2)] == [True] + [False] * 5
    assert list(program.code_addresses()) == [0]
    assert program.self_branches == []
    assert program.end_address == 4


def test_gnu_as_emits_plain_mapping_symbols(tmp_path):
    # Several sections, alignment padding and pools: still only $a and $d.
    result = assemble(LAYOUT + "        .text\n        .byte 1\n        .align 3\n"
                      "        MOV R0, #1\n", tmp_path)
    assert result.ok
    with open(result.elf_path, "rb") as f:
        names = {sym.name for sym in ELFFile(f).get_section_by_name(".symtab").iter_symbols()
                 if sym.name.startswith("$")}
    assert names == {"$a", "$d"}
    program = Program(result.elf_path)
    assert {l.name for l in program.labels} == {"_start", "msg", "vec", "value"}


def test_mapping_symbol_names():
    assert _mapping_kind("$a") == "a"
    assert _mapping_kind("$d") == "d"
    assert _mapping_kind("$t") == "t"
    assert _mapping_kind("$a.12") == "a"
    assert _mapping_kind("$d.literal") == "d"
    assert _mapping_kind("$x") is None
    assert _mapping_kind("$dx") is None
    assert _mapping_kind("$") is None
    assert _mapping_kind("data") is None
