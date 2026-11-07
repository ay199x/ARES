# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The capital-letters rule: checking lines and capitalizing whole files."""

import pytest

from ares.assembler import assemble
from ares.capitals import Offence, capitalize, check, offences
from ares.program import Program
from conftest import PROGRAMS, ROOT

MIXED = ROOT / "tests" / "data" / "mixed_case.s"


# Checking ------------------------------------------------------------------

@pytest.mark.parametrize("line, corrected", [
    ("        add r0, r1, #1", "ADD R0, R1, #1"),
    ("Add R0, Sp, #4", "ADD R0, SP, #4"),
    ("ADD R0, r1, R2", "ADD R0, R1, R2"),
    ("ldrneb r3, [r4]", "LDRNEB R3, [R4]"),
    ("addeqs r0, r0, #1", "ADDEQS R0, R0, #1"),
    ("pop {r0-r5, pc}", "POP {R0-R5, PC}"),
    ("push {r4, Lr}", "PUSH {R4, LR}"),
    ("stmfd sp!, {fp, ip, lr}", "STMFD SP!, {FP, IP, LR}"),
    ("mov r0, r1, lsl #2", "MOV R0, R1, LSL #2"),
    ("MOV R0, R1, Asr R2", "MOV R0, R1, ASR R2"),
    ("loop:   subs r0, r0, #1", "loop:   SUBS R0, R0, #1"),
    ("ldr sp, =0x3ffffff8", "LDR SP, =0x3ffffff8"),
    ("ldr r1, =covid_genome", "LDR R1, =covid_genome"),
    ("cmp r2, #'n'", "CMP R2, #'n'"),
    ("b div_loop", "B div_loop"),
    ("Svc #0x0a", "SVC #0x0a"),
    ("vadd.f32 s0, s1, s2", "VADD.F32 S0, S1, S2"),
    ("VADD.f32 S0, S1, S2", "VADD.F32 S0, S1, S2"),
    ("vcvt.f32.s32 s0, s1", "VCVT.F32.S32 S0, S1"),
    ("vld1.32 {d0-d3}, [r0:128]!", "VLD1.32 {D0-D3}, [R0:128]!"),
    ("vdup.32 q0, d1[1]", "VDUP.32 Q0, D1[1]"),
    ("msr cpsr_fc, r0", "MSR CPSR_fc, R0"),
    ("vmrs apsr_nzcv, fpscr", "VMRS APSR_nzcv, FPSCR"),
    ("mrc p15, 0, r0, c1, c0, 0", "MRC P15, 0, R0, C1, C0, 0"),
    ("count .req r4", "count .req R4"),
    ("mov r0, #1 ; mov r1, #2", "MOV R0, #1 ; MOV R1, #2"),
    ("\tadd r0, r1, #1   @ Add One  ", "ADD R0, R1, #1   @ Add One"),
    ("mov r0, #1 /* add r1 */ // sub r2", "MOV R0, #1 /* add r1 */ // sub r2"),
    ("ADDSEQ R0, R0, #1 ; ldrbeq r1, [r2]", "ADDSEQ R0, R0, #1 ; LDRBEQ R1, [R2]"),
    ("it eq", "IT eq"),
    ("mcr p15, 0, r0, cr7, Cr10, 5", "MCR P15, 0, R0, CR7, CR10, 5"),
    ("vmrs r0, fpinst", "VMRS R0, FPINST"),
    ("x .dn d0.f32", "x .dn D0.F32"),
    ("ldreqht r0, [r1] ; ldseqb r2, [r3]", "LDREQHT R0, [R1] ; LDSEQB R2, [R3]"),
    ("vdupqeq.32 q0, r0", "VDUPQEQ.32 Q0, R0"),
    ("vadd.f s0, s1, s2", "VADD.F S0, S1, S2"),
    ("ldr r0, s1", "LDR R0, s1"),
    ("bl lr", "BL lr"),
    ("blx lr", "BLX LR"),
    ("mov r0, #s1", "MOV R0, #s1"),
    ("año: add r0, r1, r2", "año: ADD R0, R1, R2"),
    ("10$: subs r0, r0, #1", "10$: SUBS R0, R0, #1"),
])
def test_instruction_offences(line, corrected):
    assert check(line) == [(1, corrected)]
    assert offences(line) == [Offence(1, corrected, True, False)]
    assert offences(line)[0].message == (
        "write instructions and registers in capitals: " + corrected)


@pytest.mark.parametrize("line, corrected", [
    (".GLOBAL _start", ".global _start"),
    ("        .Word 5", ".word 5"),
    ("msg: .ASCIZ \"Hello\"", "msg: .asciz \"Hello\""),
    ("x .REQ R4", "x .req R4"),
    (".Macro Print_It", ".macro Print_It"),
])
def test_directive_offences(line, corrected):
    assert offences(line) == [Offence(1, corrected, False, True)]
    assert offences(line)[0].message == "write directives in lowercase: " + corrected


def test_instruction_and_directive_offences_on_one_line():
    line = "data: .WORD 1 ; add r0, r0, #1"
    corrected = "data: .word 1 ; ADD R0, R0, #1"
    [offence] = offences(line)
    assert offence == Offence(1, corrected, True, True)
    assert offence.message == (
        "write instructions and registers in capitals and directives in lowercase: "
        + corrected)


@pytest.mark.parametrize("line", [
    "        ADD R0, R1, #1",
    "_start: LDR SP, =0x3FFFFFF8",
    "Loop:   B Loop",
    "        BL Print_Char",
    "        LDR R0, =myData",
    "        .global Main",
    "        MOV R0, #0xff",
    "        LDR R1, =0xabcdef",
    "        CMP R2, #'a'",
    "        MOV R0, #'\\n'",
    "        MOV R0, #1 @ add r0, r1, lsl #2",
    "        MOV R0, #1 // mov pc, lr",
    "# sub r0, r0, #1",
    "msg:    .asciz \"r0 add lsl sp\"",
    "        .byte 'a', 'b'",
    "        MSR CPSR_fc, R0",
    "        MSR CPSR_FC, R0",
    "        MRC P15, 0, R0, C1, C0, 0",
    "count   .req R4",
    "        MOV count, #3",
    "limit = 10",
    "        .macro push_pair first, second",
    "        PUSH {\\first, \\second}",
    "        push_pair r4, r5",
    "        .word a1, r0, lsl",
    "        LDR R0, =a1",
    "        DMB ish",
    "        CPSID if",
    "        MOVW R0, #:lower16:msg",
    "        BNE 1b",
    "",
])
def test_lines_that_follow_the_rule(line):
    assert check(line) == []


def test_every_offending_line_is_reported_at_once():
    text = ("        .global _start\n"
            "_start:\n"
            "        mov r0, #1\n"
            "        MOV R1, #2\n"
            "/* add r0, r0\n"
            "   sub r1 */ sub r2, r2, #3\n"
            "        .Data\n"
            "        Svc #10\n")
    assert check(text) == [(3, "MOV R0, #1"), (6, "sub r1 */ SUB R2, R2, #3"),
                           (7, ".data"), (8, "SVC #10")]


def test_labels_named_like_registers_stay_as_written():
    # Changing the case of s1 or lsl here would refer to a different symbol.
    text = "s1:     NOP\n        B s1\nlsl:    B lsl\nd2 = 8\n        LDR R0, d2\n"
    assert check(text) == []
    assert capitalize(text) == text
    assert check("        VMOV S0, s1\n") == [(1, "VMOV S0, S1")]
    # A branch target is a label even when the file does not define it.
    assert check("        B s1\n") == []


def test_comment_over_lines_inside_a_statement():
    text = ("        add r0, r1, /* the first\n"
            "                operand */ r2\n"
            "        LDR R0, /* the\n"
            "                table */ b\n")
    assert check(text) == [(1, "ADD R0, R1, /* the first"), (2, "operand */ R2")]
    assert capitalize(text) == text.replace("add r0, r1", "ADD R0, R1").replace(" r2", " R2")


def test_macro_calls_are_left_alone():
    # The macro push compares its argument as text, so LR would change the program.
    text = ("        .macro push reg\n"
            "        .ifc \\reg, lr\n"
            "        STR LR, [SP, #-4]!\n"
            "        .endif\n"
            "        .endm\n"
            "        push lr\n"
            "        Push lr\n")
    assert check(text) == []
    assert check("        push {lr}\n") == [(1, "PUSH {LR}")]


# Capitalizing --------------------------------------------------------------

def test_capitalize_changes_only_offending_tokens():
    text = ("\tadd r0, r1, #1   @ add one \n"
            ".Global main\r\n"
            "main: ldr sp, =0x3ffffff8 ; msr cpsr_c, #0xd3\n"
            "  /* mov r0\n"
            "  r1 */ \n")
    assert capitalize(text) == (
        "\tADD R0, R1, #1   @ add one \n"
        ".global main\r\n"
        "main: LDR SP, =0x3ffffff8 ; MSR CPSR_c, #0xd3\n"
        "  /* mov r0\n"
        "  r1 */ \n")


def program_files():
    return sorted(PROGRAMS.glob("*.s")) + [MIXED]


@pytest.mark.parametrize("path", program_files(), ids=lambda p: p.name)
def test_capitalize_is_idempotent_and_passes_the_check(path):
    text = path.read_text(encoding="utf-8")
    once = capitalize(text)
    assert capitalize(once) == once
    assert check(once) == []


def test_mixed_program_breaks_the_rule_on_many_lines():
    assert len(check(MIXED.read_text(encoding="utf-8"))) > 150


def sections(result):
    assert result.ok, [m.format() for m in result.messages]
    return [(s.name, s.address, s.data) for s in Program(result.elf_path).sections]


@pytest.mark.parametrize("path", program_files(), ids=lambda p: p.name)
def test_capitalized_program_assembles_to_the_same_binary(tmp_path, path):
    text = path.read_text(encoding="utf-8")
    before = sections(assemble(text, tmp_path / "before", require_capitals=False))
    after = sections(assemble(capitalize(text), tmp_path / "after"))
    assert any(name == ".text" for name, _, _ in before)
    assert after == before


SNIPPETS = {
    "macro named like an instruction": (
        "        .global _start\n"
        "        .macro push reg\n"
        "        .ifc \\reg, lr\n"
        "        STR LR, [SP, #-4]!\n"
        "        .else\n"
        "        STMFD SP!, {\\reg}\n"
        "        .endif\n"
        "        .endm\n"
        "_start:\n"
        "        push lr\n"
        "        B .\n"),
    "label made by a macro": (
        "        .global _start\n"
        "        .macro deflab n\n"
        "\\n:     NOP\n"
        "        .endm\n"
        "_start:\n"
        "        deflab s1\n"
        "        b s1\n"
        "        ldr r0, s1\n"
        "        adr r1, s1\n"
        "        mov r2, #s1 - _start\n"
        "        ldrd r2, r3, s1\n"),
}


@pytest.mark.parametrize("text", SNIPPETS.values(), ids=SNIPPETS.keys())
def test_capitalized_snippet_assembles_to_the_same_binary(tmp_path, text):
    before = sections(assemble(text, tmp_path / "before", require_capitals=False))
    after = sections(assemble(capitalize(text), tmp_path / "after"))
    assert after == before
