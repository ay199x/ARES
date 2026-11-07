# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Text Segment rows: Basic column, literal pools, data words and sources."""

import subprocess
import sys
import time

import pytest

from ares.disasm import TextRow, basic, format_address, text_rows
from conftest import ROOT

# (source instruction, Basic column) in the order they are assembled from 0.
ENCODINGS = [
    ("ADD R0, R1, R2, LSL #3", "ADD R0, R1, R2, LSL #3"),
    ("SUBS R3, R4, R5, ASR R6", "SUBS R3, R4, R5, ASR R6"),
    ("MOV R7, R8, ROR #31", "ROR R7, R8, #0x1F"),
    ("RSB R0, R0, #0", "RSB R0, R0, #0"),
    ("MVN R2, #255", "MVN R2, #0xFF"),
    ("MOVW R1, #0xBEEF", "MOVW R1, #0xBEEF"),
    ("CMP R0, #100", "CMP R0, #0x64"),
    ("LDR R0, [R1]", "LDR R0, [R1]"),
    ("LDR R0, [R1, #4]", "LDR R0, [R1, #4]"),
    ("LDR R0, [R1, #-4]!", "LDR R0, [R1, #-4]!"),
    ("LDR R0, [R1], #8", "LDR R0, [R1], #8"),
    ("LDR R0, [R1, R2, LSL #2]", "LDR R0, [R1, R2, LSL #2]"),
    ("STRB R0, [R1, -R2]", "STRB R0, [R1, -R2]"),
    ("LDRH R0, [R1, #2]", "LDRH R0, [R1, #2]"),
    ("STRD R2, R3, [SP, #-8]!", "STRD R2, R3, [SP, #-8]!"),
    ("LDMIA R0!, {R1-R4}", "LDM R0!, {R1, R2, R3, R4}"),
    ("STMDB SP!, {R4-R11, LR}", "PUSH {R4, R5, R6, R7, R8, R9, R10, R11, LR}"),
    ("PUSH {R4, LR}", "PUSH {R4, LR}"),
    ("POP {R4, PC}", "POP {R4, PC}"),
    ("B _start", "B #0"),
    ("BL _start", "BL #0"),
    ("BX LR", "BX LR"),
    ("BLX R3", "BLX R3"),
    ("BLX _start", "BLX #0"),
    ("SVC #0", "SVC #0"),
    ("SVC #10", "SVC #0xA"),
    ("MRS R0, CPSR", "MRS R0, APSR"),
    ("MSR CPSR_fc, R0", "MSR CPSR_FC, R0"),
    ("MUL R0, R1, R2", "MUL R0, R1, R2"),
    ("MLA R0, R1, R2, R3", "MLA R0, R1, R2, R3"),
    ("UMULL R0, R1, R2, R3", "UMULL R0, R1, R2, R3"),
    ("VADD.F32 S1, S0, S0", "VADD.F32 S1, S0, S0"),
    ("VMOV S0, R0", "VMOV S0, R0"),
    ("VMOV R0, R1, D2", "VMOV R0, R1, D2"),
    ("VLDR S0, [R0, #8]", "VLDR S0, [R0, #8]"),
    ("VADD.I32 Q0, Q1, Q2", "VADD.I32 Q0, Q1, Q2"),
    ("VLD1.32 {D0-D1}, [R0]!", "VLD1.32 {D0, D1}, [R0]!"),
    ("LDRNEB R0, [R1]", "LDRBNE R0, [R1]"),
    ("SUBNE R0, R0, #1", "SUBNE R0, R0, #1"),
    ("BEQ _start", "BEQ #0"),
    ("MOV R11, R12", "MOV R11, R12"),
    ("ADD R9, R10, R12, LSL #2", "ADD R9, R10, R12, LSL #2"),
    ("NOP", "NOP"),
]


def test_known_encodings(build):
    source = "        .global _start\n_start:\n" + "".join(
        f"        {instruction}\n" for instruction, _ in ENCODINGS)
    rows = text_rows(build(source), source)
    assert [r.basic for r in rows] == [b for _, b in ENCODINGS]
    assert [r.address for r in rows] == list(range(0, 4 * len(ENCODINGS), 4))
    assert [r.line for r in rows] == list(range(3, 3 + len(ENCODINGS)))
    assert rows[0].source == " 3:         ADD R0, R1, R2, LSL #3"
    assert rows[0].code == 0xE0810182


def test_basic_capitals_with_lowercase_hex_prefix():
    assert basic(0xE59F0014, 0) == "LDR R0, [PC, #0x14]"
    assert basic(0xEA000001, 0x10) == "B #0x1C"
    assert basic(0xE51F000C, 0) == "LDR R0, [PC, #-0xC]"
    assert basic(0xEE700A00, 0) == "VADD.F32 S1, S0, S0"
    assert basic(0xE1A0B00C, 0) == "MOV R11, R12"
    assert basic(0xE320F000, 0) == "NOP"


def test_basic_undecodable_word_is_data():
    assert basic(0xFFFFFFFF, 0) == ".word 0xFFFFFFFF"


def test_format_address():
    assert format_address(0) == "0x00000000"
    assert format_address(0x50000000) == "0x50000000"
    assert format_address(0xFF201000) == "0xff201000"


POOL_SOURCE = """\
        .global _start
_start:
        LDR     R0, =0x12345678
        LDR     R1, =0xCAFEBABE
        B       next
        .ltorg
next:
\tMOV     R2, #1   @ after the pool  \r
        B       .
"""


def test_literal_pool_and_code_after_ltorg(build):
    rows = text_rows(build(POOL_SOURCE), POOL_SOURCE)
    assert rows == [
        TextRow(0x00, 0xE59F0004, "LDR R0, [PC, #4]", 3, "3:         LDR     R0, =0x12345678"),
        TextRow(0x04, 0xE59F1004, "LDR R1, [PC, #4]", 4, "4:         LDR     R1, =0xCAFEBABE"),
        TextRow(0x08, 0xEA000001, "B #0x14", 5, "5:         B       next"),
        TextRow(0x0C, 0x12345678, ".word 0x12345678", None, ""),
        TextRow(0x10, 0xCAFEBABE, ".word 0xCAFEBABE", None, ""),
        TextRow(0x14, 0xE3A02001, "MOV R2, #1", 8, "8:     MOV     R2, #1   @ after the pool"),
        TextRow(0x18, 0xEAFFFFFE, "B #0x18", 9, "9:         B       ."),
    ]


# The line table has no row for this pool word (its LDR is on the line before).
POOL_AFTER_ITS_LOAD = """\
        .global _start
_start: MOV     R0, #1
        LDR     PC, =main
        .ltorg
nums:   .word   1
        .align  3
main:   MOV     R1, #2
        B       .
"""

# An 8-byte literal, then user data and zero padding.
DOUBLE_POOL = """\
        .global _start
_start: VLDR    D0, =0x1122334455667788
        B       skip
        .ltorg
        .word   0x99
        .balign 32, 0
skip:   B       .
"""


def test_literal_pool_rows_have_no_source(build):
    rows = text_rows(build(POOL_AFTER_ITS_LOAD), POOL_AFTER_ITS_LOAD)
    assert [(r.address, r.basic, r.line, r.source) for r in rows[1:4]] == [
        (0x04, "LDR PC, [PC, #-4]", 3, "3:         LDR     PC, =main"),
        (0x08, ".word 0x00000010", None, ""),
        (0x0C, ".word 0x00000001", None, ""),
    ]
    rows = text_rows(build(DOUBLE_POOL), DOUBLE_POOL)
    assert [(r.basic, r.line, r.source) for r in rows[2:5]] == [
        (".word 0x55667788", None, ""),
        (".word 0x11223344", None, ""),
        (".word 0x00000099", None, ""),
    ]
    assert rows[-1].source == "7: skip:   B       ."


def test_undecodable_instruction_is_shown_as_data(build):
    source = "        .global _start\n_start: .inst 0xFFFFFFFF\n        B .\n"
    rows = text_rows(build(source), source)
    assert [r.basic for r in rows] == [".word 0xFFFFFFFF", "B #4"]
    assert rows[0].source == "2: _start: .inst 0xFFFFFFFF"


INTERIOR_DATA = """\
        .global _start
_start: MOV     R0, #1
        B       skip
table:  .word   1, 2
        .byte   3
        .align  2
skip:   MOV     R1, #2
        B       .
"""


def test_data_between_instructions_has_no_source(build):
    rows = text_rows(build(INTERIOR_DATA), INTERIOR_DATA)
    assert [(r.address, r.basic, r.line, r.source) for r in rows] == [
        (0x00, "MOV R0, #1", 2, "2: _start: MOV     R0, #1"),
        (0x04, "B #0x14", 3, "3:         B       skip"),
        (0x08, ".word 0x00000001", None, ""),
        (0x0C, ".word 0x00000002", None, ""),
        (0x10, ".word 0x00000003", None, ""),
        (0x14, "MOV R1, #2", 7, "7: skip:   MOV     R1, #2"),
        (0x18, "B #0x18", 8, "8:         B       ."),
    ]


TRAILING_DATA = """\
/* Data after the last instruction, as in many DE1-SoC examples */
        .text
        .global _start
_start: LDR     R4, =TEST_NUM   @ address of the data
        LDR     R1, [R4]
        LDR     R2, =0x0000FFFF
END:    B       END
TEST_NUM: .word 0x103FE00F
        .hword  1, 2
        .byte   3
        .asciz  "A\\n"
        .end
"""


def test_data_after_last_instruction_has_no_source(build):
    rows = text_rows(build(TRAILING_DATA), TRAILING_DATA)
    assert [(r.address, r.basic, r.line, r.source) for r in rows[3:]] == [
        (0x0C, "B #0xC", 7, "7: END:    B       END"),
        (0x10, ".word 0x103FE00F", None, ""),
        (0x14, ".word 0x00020001", None, ""),
        (0x18, ".word 0x000A4103", None, ""),
        (0x1C, ".word 0x00000010", None, ""),        # literal pool: =TEST_NUM
        (0x20, ".word 0x0000FFFF", None, ""),        # literal pool: =0x0000FFFF
    ]


EXTRA_SECTIONS = """\
        .global _start
        .text
_start: MOV     R0, #1
        B       .
        .section .vectors, "ax"
        B       _start
        .section .tail, "ax"
last:   .byte   1, 2, 3
"""


def test_extra_executable_sections_are_disassembled(build):
    program = build(EXTRA_SECTIONS)
    rows = text_rows(program, EXTRA_SECTIONS)
    vectors = next(s for s in program.sections if s.name == ".vectors")
    tail = next(s for s in program.sections if s.name == ".tail")
    assert [(r.address, r.basic, r.source) for r in rows] == [
        (0x0, "MOV R0, #1", "3: _start: MOV     R0, #1"),
        (0x4, "B #4", "4:         B       ."),
        (vectors.address, "B #0", "6:         B       _start"),
        (tail.address, ".byte 0x01, 0x02, 0x03", ""),
    ]
    assert tail.size == 3 and rows[-1].code == 0x00030201 and rows[-1].line is None


MISALIGNED = """\
        .global _start
_start: MOV     R0, #1
        .hword  7
        B       .
"""


def test_misaligned_instruction_keeps_word_rows(build):
    # GNU as places an instruction after .hword at a half-word address.
    program = build(MISALIGNED)
    rows = text_rows(program, MISALIGNED)
    assert [(r.address, r.code, r.basic, r.line) for r in rows] == [
        (0x0, 0xE3A00001, "MOV R0, #1", 2),
        (0x4, 0xFFFE0007, ".word 0xFFFE0007", None),
        (0x8, 0x0000EAFF, ".word 0x0000EAFF", None),
    ]


ALIGN_PADDING = """\
        .global _start
_start: MOV     R0, #1
        .align  4
next:   B       .
"""


def test_alignment_padding_is_code_without_source(build):
    rows = text_rows(build(ALIGN_PADDING), ALIGN_PADDING)
    assert [(r.address, r.basic, r.line, r.source) for r in rows] == [
        (0x00, "MOV R0, #1", 2, "2: _start: MOV     R0, #1"),
        (0x04, "NOP", None, ""),
        (0x08, "NOP", None, ""),
        (0x0C, "NOP", None, ""),
        (0x10, "B #0x10", 4, "4: next:   B       ."),
    ]


ADRL = """\
        .global _start
_start: ADRL    R0, far
        B       .
far:    .word   5
"""


def test_second_word_of_adrl_has_no_source(build):
    rows = text_rows(build(ADRL), ADRL)
    assert [(r.basic, r.line, r.source) for r in rows] == [
        ("ADD R0, PC, #4", 2, "2: _start: ADRL    R0, far"),
        ("MOV R0, R0", None, ""),
        ("B #8", 3, "3:         B       ."),
        (".word 0x00000005", None, ""),
    ]


@pytest.mark.parametrize("source", [POOL_SOURCE, POOL_AFTER_ITS_LOAD, DOUBLE_POOL,
                                    INTERIOR_DATA, TRAILING_DATA, EXTRA_SECTIONS,
                                    MISALIGNED, ALIGN_PADDING, ADRL])
def test_is_code_agrees_with_rows(build, source):
    # The Bkpt column uses program.is_code(row.address).
    program = build(source)
    rows = text_rows(program, source)
    disassembled = [not r.basic.startswith(".") for r in rows]
    assert [program.is_code(r.address) for r in rows] == disassembled
    assert list(program.code_addresses()) == [
        r.address for r, code in zip(rows, disassembled) if code]


def test_rows_without_source_text(build):
    rows = text_rows(build(POOL_SOURCE), "")
    assert [r.line for r in rows] == [3, 4, 5, None, None, 8, 9]
    assert all(r.source == "" for r in rows)


def test_rows_without_line_table(build):
    program = build(TRAILING_DATA)
    program.lines = {}
    rows = text_rows(program, TRAILING_DATA)
    assert [r.basic for r in rows[:4]] == ["LDR R4, [PC, #0x14]", "LDR R1, [R4]",
                                           "LDR R2, [PC, #0x10]", "B #0xC"]
    assert all(r.line is None and r.source == "" for r in rows)


def test_program_text_rows_delegates(build):
    program = build(POOL_SOURCE)
    assert program.text_rows(POOL_SOURCE) == text_rows(program, POOL_SOURCE)


def test_runner_does_not_load_capstone():
    code = ("import sys, ares.program, ares.machine, ares.cli; "
            "print('capstone' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.stdout.strip() == "False", result.stderr


TEMPLATES = ["        ADD     R0, R0, #{n}", "        LDR     R2, [R3, #{n}]",
             "        STR     R2, [R3], #4", "        SUBS    R5, R5, #1"]


def _big_program(count):
    lines = ["        .global _start", "_start:"]
    for i in range(count):
        if i % 500 == 499:
            lines += [f"        B       next{i}", "        .ltorg", f"next{i}:"]
        elif i % 100 == 0:
            lines.append(f"        LDR     R1, =0x{i:08X}")
        else:
            lines.append(TEMPLATES[i % 4].format(n=i % 256))
    lines += ["        B       .", "values: .word 1, 2, 3"]
    return "\n".join(lines) + "\n"


@pytest.mark.serial
def test_text_rows_speed(build):
    source = _big_program(5000)
    program = build(source)
    start = time.perf_counter()
    rows = text_rows(program, source)
    elapsed = time.perf_counter() - start
    assert sum(1 for r in rows if program.is_code(r.address)) == 5001
    assert rows[-4].source == f"{len(source.splitlines()) - 1}:         B       ."
    assert elapsed < 0.5, f"text_rows took {elapsed:.3f} s"


@pytest.mark.serial
def test_text_rows_speed_with_large_data_block(build):
    source = "        .global _start\n_start: B .\nstack:  .space 0x10000\n"
    program = build(source)
    start = time.perf_counter()
    rows = text_rows(program, source)
    elapsed = time.perf_counter() - start
    assert len(rows) == 1 + 0x10000 // 4
    assert rows[-1] == TextRow(0x10000, 0, ".word 0x00000000", None, "")
    assert elapsed < 0.5, f"text_rows took {elapsed:.3f} s"
