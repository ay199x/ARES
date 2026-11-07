# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Source tokenizer: token kinds, statements, comments and instruction mnemonics."""

import os
import re
import subprocess
import sys
import time

import capstone.arm_const as arm_const
import pytest

from ares.assembler import AS_OPTIONS, ERROR, parse_assembler_output
from ares.tokens import (CHAR, COMMENT, CONDITIONS, DIRECTIVE, LABEL_DEF, MNEMONIC, NUMBER,
                         PUNCT, REGISTER, SHIFT, STRING, SYMBOL, Token, is_mnemonic,
                         mnemonic_base, mnemonic_forms, tokenize, tokenize_line)
from ares.toolchain import ASSEMBLER, tool_path
from conftest import ROOT

MIXED = ROOT / "tests" / "data" / "mixed_case.s"


def pieces(line, in_comment=False, macros=frozenset()):
    """(kind, text) for every token of line."""
    tokens, _ = tokenize_line(line, in_comment, macros)
    return [(t.kind, line[t.start:t.end]) for t in tokens]


# Every token kind, on lines written for CPUlator's ARMv7 system ------------

@pytest.mark.parametrize("line, expected", [
    ("    LDR SP, =0x3FFFFFF8",
     [(MNEMONIC, "LDR"), (REGISTER, "SP"), (PUNCT, ","), (NUMBER, "=0x3FFFFFF8")]),
    ("    MOV R5, #0              @ R5 = Total Quality Score",
     [(MNEMONIC, "MOV"), (REGISTER, "R5"), (PUNCT, ","), (NUMBER, "#0"),
      (COMMENT, "@ R5 = Total Quality Score")]),
    ("    LDR R1, =covid_genome   @ R1 = Main Genome Pointer",
     [(MNEMONIC, "LDR"), (REGISTER, "R1"), (PUNCT, ","), (NUMBER, "=covid_genome"),
      (COMMENT, "@ R1 = Main Genome Pointer")]),
    ("    LDR R8, =250",
     [(MNEMONIC, "LDR"), (REGISTER, "R8"), (PUNCT, ","), (NUMBER, "=250")]),
    ("scan_loop_unrolled:", [(LABEL_DEF, "scan_loop_unrolled:")]),
    ("    @ --- BLOCK 1 ---", [(COMMENT, "@ --- BLOCK 1 ---")]),
    ("    LDRB R2, [R1], #1       @ Load char 1",
     [(MNEMONIC, "LDRB"), (REGISTER, "R2"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R1"),
      (PUNCT, "]"), (PUNCT, ","), (NUMBER, "#1"), (COMMENT, "@ Load char 1")]),
    ("    CMP R2, #'N'            @ Is it 'N'?",
     [(MNEMONIC, "CMP"), (REGISTER, "R2"), (PUNCT, ","), (NUMBER, "#"), (CHAR, "'N'"),
      (COMMENT, "@ Is it 'N'?")]),
    ("    LDRNEB R3, [R4]",
     [(MNEMONIC, "LDRNEB"), (REGISTER, "R3"), (PUNCT, ","), (PUNCT, "["),
      (REGISTER, "R4"), (PUNCT, "]")]),
    ("    SUBNE R3, R3, #33",
     [(MNEMONIC, "SUBNE"), (REGISTER, "R3"), (PUNCT, ","), (REGISTER, "R3"),
      (PUNCT, ","), (NUMBER, "#33")]),
    ("    BEQ do_print", [(MNEMONIC, "BEQ"), (SYMBOL, "do_print")]),
    ("    B div_loop", [(MNEMONIC, "B"), (SYMBOL, "div_loop")]),
    ("    BL print_char", [(MNEMONIC, "BL"), (SYMBOL, "print_char")]),
    ("    POP {R0-R5, PC}",
     [(MNEMONIC, "POP"), (PUNCT, "{"), (REGISTER, "R0"), (PUNCT, "-"), (REGISTER, "R5"),
      (PUNCT, ","), (REGISTER, "PC"), (PUNCT, "}")]),
    ("    PUSH {R1, LR}",
     [(MNEMONIC, "PUSH"), (PUNCT, "{"), (REGISTER, "R1"), (PUNCT, ","), (REGISTER, "LR"),
      (PUNCT, "}")]),
    ("    STRB R0, [R1]",
     [(MNEMONIC, "STRB"), (REGISTER, "R0"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R1"),
      (PUNCT, "]")]),
    (".global _start", [(DIRECTIVE, ".global"), (SYMBOL, "_start")]),
    ("_start:", [(LABEL_DEF, "_start:")]),
    (".data", [(DIRECTIVE, ".data")]),
    (".balign 4", [(DIRECTIVE, ".balign"), (NUMBER, "4")]),
    ("divisors: .word 100000, 10000, 1000, 100, 10, 1, 0",
     [(LABEL_DEF, "divisors:"), (DIRECTIVE, ".word"), (NUMBER, "100000"), (PUNCT, ","),
      (NUMBER, "10000"), (PUNCT, ","), (NUMBER, "1000"), (PUNCT, ","), (NUMBER, "100"),
      (PUNCT, ","), (NUMBER, "10"), (PUNCT, ","), (NUMBER, "1"), (PUNCT, ","),
      (NUMBER, "0")]),
    ('covid_genome: .asciz "ATTAAAGGTTTATACCTTCC"',
     [(LABEL_DEF, "covid_genome:"), (DIRECTIVE, ".asciz"),
      (STRING, '"ATTAAAGGTTTATACCTTCC"')]),
    ('fastq_scores: .asciz "FF@?AA><BF<I@G@EF@>H?D<<IDF;B:G@E!"',
     [(LABEL_DEF, "fastq_scores:"), (DIRECTIVE, ".asciz"),
      (STRING, '"FF@?AA><BF<I@G@EF@>H?D<<IDF;B:G@E!"')]),
    ("@ ==========================", [(COMMENT, "@ ==========================")]),
    ("        MRS R0, CPSR", [(MNEMONIC, "MRS"), (REGISTER, "R0"), (PUNCT, ","),
                              (REGISTER, "CPSR")]),
    ("        VADD.F32 S0, S1, S2",
     [(MNEMONIC, "VADD.F32"), (REGISTER, "S0"), (PUNCT, ","), (REGISTER, "S1"),
      (PUNCT, ","), (REGISTER, "S2")]),
    ("        VMOV R0, R1, D0",
     [(MNEMONIC, "VMOV"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "R1"), (PUNCT, ","),
      (REGISTER, "D0")]),
    ("        MOV R0, #1  // text", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                                     (NUMBER, "#1"), (COMMENT, "// text")]),
    ("        MOV R0, #1  /* text */", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                                        (NUMBER, "#1"), (COMMENT, "/* text */")]),
])
def test_token_kinds_of_cpulator_lines(line, expected):
    assert pieces(line) == expected


def test_token_columns():
    tokens, in_comment = tokenize_line("  ADD R0, R1, #-1 @ x  ")
    assert tokens == [Token(MNEMONIC, 2, 5), Token(REGISTER, 6, 8), Token(PUNCT, 8, 9),
                      Token(REGISTER, 10, 12), Token(PUNCT, 12, 13), Token(NUMBER, 14, 17),
                      Token(COMMENT, 18, 21)]
    assert in_comment is False
    assert tokenize_line("") == ([], False)
    assert tokenize_line("   \t ") == ([], False)


def test_tokens_cover_every_non_blank_character():
    text = MIXED.read_text(encoding="utf-8")
    for line, tokens in zip(text.split("\n"), tokenize(text)):
        covered = [False] * len(line)
        for t in tokens:
            assert 0 <= t.start < t.end <= len(line)
            assert not any(covered[t.start:t.end]), line
            covered[t.start:t.end] = [True] * (t.end - t.start)
        assert all(covered[i] or line[i].isspace() for i in range(len(line))), line


# Comments ------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("@ whole line", [(COMMENT, "@ whole line")]),
    ("// whole line", [(COMMENT, "// whole line")]),
    ("# whole line", [(COMMENT, "# whole line")]),
    ("   # indented", [(COMMENT, "# indented")]),
    ("loop: # after a label", [(LABEL_DEF, "loop:"), (COMMENT, "# after a label")]),
    ("NOP ; # after a semicolon",
     [(MNEMONIC, "NOP"), (PUNCT, ";"), (COMMENT, "# after a semicolon")]),
    ("MOV R0, #8//2", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#8"),
                       (COMMENT, "//2")]),
    ("MOV R0, #8 / 2", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#8"),
                        (PUNCT, "/"), (NUMBER, "2")]),
    ("MOV R0, #'@' @ c", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                          (NUMBER, "#"), (CHAR, "'@'"), (COMMENT, "@ c")]),
    ('.ascii "a@b;c//d/*e" @ c', [(DIRECTIVE, ".ascii"), (STRING, '"a@b;c//d/*e"'),
                                  (COMMENT, "@ c")]),
    ("label: /* x */ ADD R0, R0, #1",
     [(LABEL_DEF, "label:"), (COMMENT, "/* x */"), (MNEMONIC, "ADD"), (REGISTER, "R0"),
      (PUNCT, ","), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#1")]),
])
def test_comments(line, expected):
    assert pieces(line) == expected


def test_multi_line_comment_state():
    tokens, in_comment = tokenize_line("MOV R0, #1 /* start")
    assert tokens[-1] == Token(COMMENT, 11, 19)
    assert in_comment
    tokens, still = tokenize_line("   ADD R0, R1 still comment", in_comment)
    assert tokens == [Token(COMMENT, 3, 27)]
    assert still == in_comment
    assert tokenize_line("", True) == ([], True)
    line = "  end */ SUB R2, R2, #1 @ done"
    assert pieces(line, True) == [
        (COMMENT, "end */"), (MNEMONIC, "SUB"), (REGISTER, "R2"), (PUNCT, ","),
        (REGISTER, "R2"), (PUNCT, ","), (NUMBER, "#1"), (COMMENT, "@ done")]
    assert tokenize_line(line, True)[1] is False
    assert tokenize_line("NOP ; /* a")[1] == tokenize_line("/* a")[1]


def test_tokenize_text_carries_comment_state():
    text = "MOV R0, #1\n/* a\nadd r0\n*/ B .\n"
    assert [[(t.kind) for t in line] for line in tokenize(text)] == [
        [MNEMONIC, REGISTER, PUNCT, NUMBER], [COMMENT], [COMMENT], [COMMENT, MNEMONIC, SYMBOL],
        []]


def text_pieces(text):
    """(kind, text) for every token of every line of text."""
    return [[(t.kind, line[t.start:t.end]) for t in tokens]
            for line, tokens in zip(text.split("\n"), tokenize(text))]


@pytest.mark.parametrize("text, after", [
    # The assembler reads a comment as a space, so the statement goes on.
    ("ADD r0, r1, /* first\n operand */ r2", [(COMMENT, "operand */"), (REGISTER, "r2")]),
    ("MOV R0, /* x\ny */ #1", [(COMMENT, "y */"), (NUMBER, "#1")]),
    ("ADD R0, R1 /* a\n */ , R2", [(COMMENT, "*/"), (PUNCT, ","), (REGISTER, "R2")]),
    ("LDR R0, /* the\n the table */ b", [(COMMENT, "the table */"), (SYMBOL, "b")]),
    ("NOP /* a\n */ NOP", [(COMMENT, "*/"), (SYMBOL, "NOP")]),
    # A comment before or between statements leaves the next one at its start.
    ("NOP\n/* a\n */ NOP", [(COMMENT, "*/"), (MNEMONIC, "NOP")]),
    ("lab: /* a\n */ NOP", [(COMMENT, "*/"), (MNEMONIC, "NOP")]),
    ("NOP ; /* a\n */ # comment", [(COMMENT, "*/"), (COMMENT, "# comment")]),
])
def test_comment_over_lines_inside_a_statement(text, after):
    assert text_pieces(text)[-1] == after


# Statements ----------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("MOV R0, #1 ; add r1, r2, r3",
     [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#1"), (PUNCT, ";"),
      (MNEMONIC, "add"), (REGISTER, "r1"), (PUNCT, ","), (REGISTER, "r2"), (PUNCT, ","),
      (REGISTER, "r3")]),
    ("a: b: NOP", [(LABEL_DEF, "a:"), (LABEL_DEF, "b:"), (MNEMONIC, "NOP")]),
    ("lab2 : NOP", [(LABEL_DEF, "lab2 :"), (MNEMONIC, "NOP")]),
    (".Lloop:", [(LABEL_DEF, ".Lloop:")]),
    # The assembler takes every character above 0x7F as a letter of a name.
    ("año: ADD R0, R1, R2", [(LABEL_DEF, "año:"), (MNEMONIC, "ADD"), (REGISTER, "R0"),
                             (PUNCT, ","), (REGISTER, "R1"), (PUNCT, ","), (REGISTER, "R2")]),
    ("B año", [(MNEMONIC, "B"), (SYMBOL, "año")]),
    ("NOP ; étiquette: NOP", [(MNEMONIC, "NOP"), (PUNCT, ";"), (LABEL_DEF, "étiquette:"),
                              (MNEMONIC, "NOP")]),
    ("10$: SUBS R0, R0, #1", [(LABEL_DEF, "10$:"), (MNEMONIC, "SUBS"), (REGISTER, "R0"),
                              (PUNCT, ","), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#1")]),
    ("BNE 10$", [(MNEMONIC, "BNE"), (SYMBOL, "10$")]),
    ("1:      SUBS R0, R0, #1",
     [(LABEL_DEF, "1:"), (MNEMONIC, "SUBS"), (REGISTER, "R0"), (PUNCT, ","),
      (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#1")]),
    ("BNE 1b ; BGT 2f", [(MNEMONIC, "BNE"), (SYMBOL, "1b"), (PUNCT, ";"),
                         (MNEMONIC, "BGT"), (SYMBOL, "2f")]),
    ("B .", [(MNEMONIC, "B"), (SYMBOL, ".")]),
    ("B .-8", [(MNEMONIC, "B"), (SYMBOL, "."), (PUNCT, "-"), (NUMBER, "8")]),
    ("limit = 10", [(SYMBOL, "limit"), (PUNCT, "="), (NUMBER, "10")]),
    ("size=end-start", [(SYMBOL, "size"), (PUNCT, "="), (SYMBOL, "end"), (PUNCT, "-"),
                        (SYMBOL, "start")]),
    (". = . + 4", [(SYMBOL, "."), (PUNCT, "="), (SYMBOL, "."), (PUNCT, "+"),
                   (NUMBER, "4")]),
    ("count .req r4", [(SYMBOL, "count"), (DIRECTIVE, ".req"), (REGISTER, "r4")]),
    ("acc .dn d7", [(SYMBOL, "acc"), (DIRECTIVE, ".dn"), (REGISTER, "d7")]),
    ("vec .qn q3", [(SYMBOL, "vec"), (DIRECTIVE, ".qn"), (REGISTER, "q3")]),
    ("x .REQ R4", [(SYMBOL, "x"), (DIRECTIVE, ".REQ"), (REGISTER, "R4")]),
    (".unreq count", [(DIRECTIVE, ".unreq"), (SYMBOL, "count")]),
    ("MOV count, #3", [(MNEMONIC, "MOV"), (SYMBOL, "count"), (PUNCT, ","), (NUMBER, "#3")]),
    (".equ step, 4", [(DIRECTIVE, ".equ"), (SYMBOL, "step"), (PUNCT, ","), (NUMBER, "4")]),
    (".section .vectors, \"ax\"", [(DIRECTIVE, ".section"), (SYMBOL, ".vectors"),
                                   (PUNCT, ","), (STRING, '"ax"')]),
    (".type main, %function", [(DIRECTIVE, ".type"), (SYMBOL, "main"), (PUNCT, ","),
                               (PUNCT, "%"), (SYMBOL, "function")]),
])
def test_statements(line, expected):
    assert pieces(line) == expected


def test_macros():
    assert pieces(".macro push_pair first, second=r5") == [
        (DIRECTIVE, ".macro"), (SYMBOL, "push_pair"), (SYMBOL, "first"), (PUNCT, ","),
        (SYMBOL, "second"), (PUNCT, "="), (SYMBOL, "r5")]
    assert pieces("        PUSH {\\first, \\second}") == [
        (MNEMONIC, "PUSH"), (PUNCT, "{"), (SYMBOL, "\\first"), (PUNCT, ","),
        (SYMBOL, "\\second"), (PUNCT, "}")]
    assert pieces("skip\\@: B skip\\@") == [
        (LABEL_DEF, "skip\\@:"), (MNEMONIC, "B"), (SYMBOL, "skip\\@")]
    assert pieces("\\name\\()_end: LDR R0, =\\name") == [
        (LABEL_DEF, "\\name\\()_end:"), (MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","),
        (NUMBER, "=\\name")]
    assert pieces(".endm") == [(DIRECTIVE, ".endm")]
    # A macro invocation is not an instruction: its operands are left as symbols.
    assert pieces("push_pair r4, r5") == [
        (SYMBOL, "push_pair"), (SYMBOL, "r4"), (PUNCT, ","), (SYMBOL, "r5")]
    assert pieces("ADDD R0, R1") == [(SYMBOL, "ADDD"), (SYMBOL, "R0"), (PUNCT, ","),
                                     (SYMBOL, "R1")]


def test_macros_named_like_instructions():
    # From its .macro line on, the name calls the macro in any case.
    text = "push {lr}\n.MACRO Push reg\n.endm\npush lr\nlab: PUSH {LR} ; push r0, r1"
    assert text_pieces(text) == [
        [(MNEMONIC, "push"), (PUNCT, "{"), (REGISTER, "lr"), (PUNCT, "}")],
        [(DIRECTIVE, ".MACRO"), (SYMBOL, "Push"), (SYMBOL, "reg")],
        [(DIRECTIVE, ".endm")],
        [(SYMBOL, "push"), (SYMBOL, "lr")],
        [(LABEL_DEF, "lab:"), (SYMBOL, "PUSH"), (PUNCT, "{"), (SYMBOL, "LR"), (PUNCT, "}"),
         (PUNCT, ";"), (SYMBOL, "push"), (SYMBOL, "r0"), (PUNCT, ","), (SYMBOL, "r1")]]
    assert pieces("ADD r0, r1", macros={"ADD"}) == [
        (SYMBOL, "ADD"), (SYMBOL, "r0"), (PUNCT, ","), (SYMBOL, "r1")]


# Operands ------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("MOV R0, R1, LSL #2",
     [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "R1"), (PUNCT, ","),
      (SHIFT, "LSL"), (NUMBER, "#2")]),
    ("ADD R0, R1, R2, asr r3",
     [(MNEMONIC, "ADD"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "R1"), (PUNCT, ","),
      (REGISTER, "R2"), (PUNCT, ","), (SHIFT, "asr"), (REGISTER, "r3")]),
    ("MOV R0, R1, RRX", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                         (REGISTER, "R1"), (PUNCT, ","), (SHIFT, "RRX")]),
    ("LDR R0, [R1, R2, LSR #3]!",
     [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R1"),
      (PUNCT, ","), (REGISTER, "R2"), (PUNCT, ","), (SHIFT, "LSR"), (NUMBER, "#3"),
      (PUNCT, "]"), (PUNCT, "!")]),
    ("LDMFD SP!, {R0-R12, LR}^",
     [(MNEMONIC, "LDMFD"), (REGISTER, "SP"), (PUNCT, "!"), (PUNCT, ","), (PUNCT, "{"),
      (REGISTER, "R0"), (PUNCT, "-"), (REGISTER, "R12"), (PUNCT, ","), (REGISTER, "LR"),
      (PUNCT, "}"), (PUNCT, "^")]),
    ("MOV R0, #0x1F", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                       (NUMBER, "#0x1F")]),
    ("MVN R0, #-1", [(MNEMONIC, "MVN"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#-1")]),
    ("MOV R0, #'\\n'", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#"),
                        (CHAR, "'\\n'")]),
    ("MOV R0, #(1 << 4)",
     [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#"), (PUNCT, "("),
      (NUMBER, "1"), (PUNCT, "<"), (PUNCT, "<"), (NUMBER, "4"), (PUNCT, ")")]),
    ("VMOV.F32 S0, #-1.5", [(MNEMONIC, "VMOV.F32"), (REGISTER, "S0"), (PUNCT, ","),
                            (NUMBER, "#-1.5")]),
    ("MOVW R0, #:lower16:msg",
     [(MNEMONIC, "MOVW"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#"), (PUNCT, ":"),
      (SYMBOL, "lower16"), (PUNCT, ":"), (SYMBOL, "msg")]),
    ("LDR R0, =label + 4 @ c", [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","),
                                (NUMBER, "=label + 4"), (COMMENT, "@ c")]),
    ("LDR R0, = 0x10", [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","),
                        (NUMBER, "= 0x10")]),
    ("LDR R0, =';' ; NOP", [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","),
                            (NUMBER, "=';'"), (PUNCT, ";"), (MNEMONIC, "NOP")]),
    ("LDR R0, =a1", [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "=a1")]),
    (".word a1, r0, 0b101, 017, 1f",
     [(DIRECTIVE, ".word"), (SYMBOL, "a1"), (PUNCT, ","), (SYMBOL, "r0"), (PUNCT, ","),
      (NUMBER, "0b101"), (PUNCT, ","), (NUMBER, "017"), (PUNCT, ","), (SYMBOL, "1f")]),
    (".byte 'x', ';', '@', 0",
     [(DIRECTIVE, ".byte"), (CHAR, "'x'"), (PUNCT, ","), (CHAR, "';'"), (PUNCT, ","),
      (CHAR, "'@'"), (PUNCT, ","), (NUMBER, "0")]),
    (".float 1.5, 0f2.5, -3e2",
     [(DIRECTIVE, ".float"), (NUMBER, "1.5"), (PUNCT, ","), (NUMBER, "0f2.5"),
      (PUNCT, ","), (PUNCT, "-"), (NUMBER, "3e2")]),
    ('.asciz "say \\"hi\\"\\n"', [(DIRECTIVE, ".asciz"), (STRING, '"say \\"hi\\"\\n"')]),
    ('.ascii "unterminated', [(DIRECTIVE, ".ascii"), (STRING, '"unterminated')]),
])
def test_operands(line, expected):
    assert pieces(line) == expected


@pytest.mark.parametrize("line, expected", [
    ("VLD1.32 {D0-D3}, [R0:128]!",
     [(MNEMONIC, "VLD1.32"), (PUNCT, "{"), (REGISTER, "D0"), (PUNCT, "-"), (REGISTER, "D3"),
      (PUNCT, "}"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R0"), (PUNCT, ":"),
      (NUMBER, "128"), (PUNCT, "]"), (PUNCT, "!")]),
    ("VDUP.32 Q0, D1[1]",
     [(MNEMONIC, "VDUP.32"), (REGISTER, "Q0"), (PUNCT, ","), (REGISTER, "D1"), (PUNCT, "["),
      (NUMBER, "1"), (PUNCT, "]")]),
    ("VLD1.8 {D0[]}, [R1]",
     [(MNEMONIC, "VLD1.8"), (PUNCT, "{"), (REGISTER, "D0"), (PUNCT, "["), (PUNCT, "]"),
      (PUNCT, "}"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R1"), (PUNCT, "]")]),
    ("VCVT.F32.S32 S0, S31", [(MNEMONIC, "VCVT.F32.S32"), (REGISTER, "S0"), (PUNCT, ","),
                              (REGISTER, "S31")]),
    ("VMUL.F64 D0, D16, D31", [(MNEMONIC, "VMUL.F64"), (REGISTER, "D0"), (PUNCT, ","),
                               (REGISTER, "D16"), (PUNCT, ","), (REGISTER, "D31")]),
    ("VADD.I32 Q0, Q14, Q15", [(MNEMONIC, "VADD.I32"), (REGISTER, "Q0"), (PUNCT, ","),
                               (REGISTER, "Q14"), (PUNCT, ","), (REGISTER, "Q15")]),
    ("MSR CPSR_f, R0", [(MNEMONIC, "MSR"), (REGISTER, "CPSR_f"), (PUNCT, ","),
                        (REGISTER, "R0")]),
    ("msr cpsr_fc, r0", [(MNEMONIC, "msr"), (REGISTER, "cpsr_fc"), (PUNCT, ","),
                         (REGISTER, "r0")]),
    ("MSR SPSR, R1", [(MNEMONIC, "MSR"), (REGISTER, "SPSR"), (PUNCT, ","), (REGISTER, "R1")]),
    ("VMRS APSR_nzcv, FPSCR", [(MNEMONIC, "VMRS"), (REGISTER, "APSR_nzcv"), (PUNCT, ","),
                               (REGISTER, "FPSCR")]),
    ("VMRS R0, FPEXC ; VMRS R1, FPSID ; VMRS R2, MVFR0 ; VMRS R3, MVFR1",
     [(MNEMONIC, "VMRS"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "FPEXC"), (PUNCT, ";"),
      (MNEMONIC, "VMRS"), (REGISTER, "R1"), (PUNCT, ","), (REGISTER, "FPSID"), (PUNCT, ";"),
      (MNEMONIC, "VMRS"), (REGISTER, "R2"), (PUNCT, ","), (REGISTER, "MVFR0"), (PUNCT, ";"),
      (MNEMONIC, "VMRS"), (REGISTER, "R3"), (PUNCT, ","), (REGISTER, "MVFR1")]),
    ("MRC p15, 0, r0, c1, c0, 0",
     [(MNEMONIC, "MRC"), (REGISTER, "p15"), (PUNCT, ","), (NUMBER, "0"), (PUNCT, ","),
      (REGISTER, "r0"), (PUNCT, ","), (REGISTER, "c1"), (PUNCT, ","), (REGISTER, "c0"),
      (PUNCT, ","), (NUMBER, "0")]),
    ("MCRREQ P15, 0, R0, R1, C2",
     [(MNEMONIC, "MCRREQ"), (REGISTER, "P15"), (PUNCT, ","), (NUMBER, "0"), (PUNCT, ","),
      (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "R1"), (PUNCT, ","), (REGISTER, "C2")]),
    ("LDCL p14, c5, [R1, #4]",
     [(MNEMONIC, "LDCL"), (REGISTER, "p14"), (PUNCT, ","), (REGISTER, "c5"), (PUNCT, ","),
      (PUNCT, "["), (REGISTER, "R1"), (PUNCT, ","), (NUMBER, "#4"), (PUNCT, "]")]),
    ("MCR p15, 0, r0, cr7, CR10, 5",
     [(MNEMONIC, "MCR"), (REGISTER, "p15"), (PUNCT, ","), (NUMBER, "0"), (PUNCT, ","),
      (REGISTER, "r0"), (PUNCT, ","), (REGISTER, "cr7"), (PUNCT, ","), (REGISTER, "CR10"),
      (PUNCT, ","), (NUMBER, "5")]),
    # p and c names are registers only in coprocessor instructions.
    ("MOV c1, p15", [(MNEMONIC, "MOV"), (SYMBOL, "c1"), (PUNCT, ","), (SYMBOL, "p15")]),
    ("MRC p16, 0, R0, c16, cr16", [(MNEMONIC, "MRC"), (SYMBOL, "p16"), (PUNCT, ","),
                                   (NUMBER, "0"), (PUNCT, ","), (REGISTER, "R0"), (PUNCT, ","),
                                   (SYMBOL, "c16"), (PUNCT, ","), (SYMBOL, "cr16")]),
    ("VMRS R0, FPINST ; VMRS R1, fpinst2",
     [(MNEMONIC, "VMRS"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "FPINST"), (PUNCT, ";"),
      (MNEMONIC, "VMRS"), (REGISTER, "R1"), (PUNCT, ","), (REGISTER, "fpinst2")]),
    # A Neon register may carry a data type.
    ("x .dn d0.f32", [(SYMBOL, "x"), (DIRECTIVE, ".dn"), (REGISTER, "d0.f32")]),
    ("VADD D0.F32, D1.F32, q2.i16",
     [(MNEMONIC, "VADD"), (REGISTER, "D0.F32"), (PUNCT, ","), (REGISTER, "D1.F32"),
      (PUNCT, ","), (REGISTER, "q2.i16")]),
    ("VMOV D0.X32, R0.F32", [(MNEMONIC, "VMOV"), (SYMBOL, "D0.X32"), (PUNCT, ","),
                             (SYMBOL, "R0.F32")]),
])
def test_neon_psr_and_coprocessor_operands(line, expected):
    assert pieces(line) == expected


@pytest.mark.parametrize("line, expected", [
    # A branch target is always a label, whatever its name.
    ("B c1 ; BL p15", [(MNEMONIC, "B"), (SYMBOL, "c1"), (PUNCT, ";"), (MNEMONIC, "BL"),
                       (SYMBOL, "p15")]),
    ("B s1", [(MNEMONIC, "B"), (SYMBOL, "s1")]),
    ("BLEQ lr", [(MNEMONIC, "BLEQ"), (SYMBOL, "lr")]),
    ("BL d2", [(MNEMONIC, "BL"), (SYMBOL, "d2")]),
    # BLX takes a core register or a label.
    ("BLX lr", [(MNEMONIC, "BLX"), (REGISTER, "lr")]),
    ("BLXNE R3", [(MNEMONIC, "BLXNE"), (REGISTER, "R3")]),
    ("BLX s1", [(MNEMONIC, "BLX"), (SYMBOL, "s1")]),
    # The last operand of an address instruction, outside [ ], is a label.
    ("ADR R0, d31", [(MNEMONIC, "ADR"), (REGISTER, "R0"), (PUNCT, ","), (SYMBOL, "d31")]),
    ("LDR r0, s1 @ c", [(MNEMONIC, "LDR"), (REGISTER, "r0"), (PUNCT, ","), (SYMBOL, "s1"),
                        (COMMENT, "@ c")]),
    ("STRB R0, lr + 4", [(MNEMONIC, "STRB"), (REGISTER, "R0"), (PUNCT, ","), (SYMBOL, "lr"),
                         (PUNCT, "+"), (NUMBER, "4")]),
    ("LDRD R0, R1, r2", [(MNEMONIC, "LDRD"), (REGISTER, "R0"), (PUNCT, ","), (REGISTER, "R1"),
                         (PUNCT, ","), (SYMBOL, "r2")]),
    ("LDRD R0, R1, [R2]", [(MNEMONIC, "LDRD"), (REGISTER, "R0"), (PUNCT, ","),
                           (REGISTER, "R1"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R2"),
                           (PUNCT, "]")]),
    ("LDR R0, [R1], R2", [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","), (PUNCT, "["),
                          (REGISTER, "R1"), (PUNCT, "]"), (PUNCT, ","), (REGISTER, "R2")]),
    ("VLDR D0, d1 ; NOP", [(MNEMONIC, "VLDR"), (REGISTER, "D0"), (PUNCT, ","), (SYMBOL, "d1"),
                           (PUNCT, ";"), (MNEMONIC, "NOP")]),
    ("PLD r1", [(MNEMONIC, "PLD"), (SYMBOL, "r1")]),
    ("LDC p14, c5, s1", [(MNEMONIC, "LDC"), (REGISTER, "p14"), (PUNCT, ","), (REGISTER, "c5"),
                         (PUNCT, ","), (SYMBOL, "s1")]),
    # A name after # is the value of a symbol, up to the end of the operand.
    ("MOV R0, #s1 - lr", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","), (NUMBER, "#"),
                          (SYMBOL, "s1"), (PUNCT, "-"), (SYMBOL, "lr")]),
    ("LDR R0, [R1, #d1], R2",
     [(MNEMONIC, "LDR"), (REGISTER, "R0"), (PUNCT, ","), (PUNCT, "["), (REGISTER, "R1"),
      (PUNCT, ","), (NUMBER, "#"), (SYMBOL, "d1"), (PUNCT, "]"), (PUNCT, ","),
      (REGISTER, "R2")]),
    ("MOV R0, R1, LSL #2 ; MOV R2, R3", [(MNEMONIC, "MOV"), (REGISTER, "R0"), (PUNCT, ","),
                                         (REGISTER, "R1"), (PUNCT, ","), (SHIFT, "LSL"),
                                         (NUMBER, "#2"), (PUNCT, ";"), (MNEMONIC, "MOV"),
                                         (REGISTER, "R2"), (PUNCT, ","), (REGISTER, "R3")]),
])
def test_registers_only_where_the_instruction_reads_one(line, expected):
    assert pieces(line) == expected


@pytest.mark.parametrize("name", [
    *(f"R{n}" for n in range(16)), "SP", "LR", "PC", "FP", "IP", "SB", "SL",
    "A1", "A2", "A3", "A4", *(f"V{n}" for n in range(1, 9)),
    "CPSR", "SPSR", "APSR", "APSR_nzcvq", "CPSR_fsxc", "SPSR_c", "FPSCR", "FPEXC",
    "FPSID", "FPINST", "FPINST2", "MVFR0", "MVFR1", *(f"S{n}" for n in range(32)),
    *(f"D{n}" for n in range(32)), *(f"Q{n}" for n in range(16)),
])
def test_register_names_in_any_case(name):
    for spelling in (name, name.lower(), name.capitalize()):
        assert pieces(f"MOV {spelling}, R0")[1] == (REGISTER, spelling)


@pytest.mark.parametrize("word", ["R16", "S32", "D32", "Q16", "V0", "V9", "A0", "A5",
                                  "CPSR_", "XPSR", "r0x", "SPX", "MVFR2", "D0.F32.F32"])
def test_not_register_names(word):
    assert pieces(f"MOV R0, {word}")[3] == (SYMBOL, word)


@pytest.mark.parametrize("shift", ["LSL", "LSR", "ASR", "ROR", "RRX", "ASL", "lsl", "Ror"])
def test_shift_names(shift):
    assert pieces(f"MOV R0, R1, {shift} #1")[5] == (SHIFT, shift)


# Instruction mnemonics -----------------------------------------------------

@pytest.mark.parametrize("word", [
    "ADD", "add", "Add", "ADDS", "ADDEQ", "ADDSEQ", "ADDEQS", "SUBNE", "BEQ", "BL", "BLLT",
    "BX", "BLX", "SVC", "SWI", "PUSH", "POP", "NOP", "MOVS", "MOVW", "MOVT", "MVNS", "CMP",
    "TST", "TEQ", "CMN", "LSL", "LSLS", "LSLEQS", "ASR", "RRX", "NEG", "ADR", "ADRL",
    "LDR", "LDRB", "LDRNEB", "LDRBNE", "LDREQB", "LDREQSH", "LDRSHEQ", "LDRH", "LDRSB",
    "LDRD", "STRD", "STRH", "STREQH", "LDRT", "LDRBT", "LDREX", "STREXB", "LDM", "LDMIA",
    "LDMFD", "LDMEQFD", "STMFD", "STMEQFD", "STMDB", "STMIB", "STMEA", "SWP", "SWPB",
    "SWPEQB", "MUL", "MULS", "MLA", "MLS", "UMULL", "UMULLEQS", "SMLAL", "SMULLS",
    "SMLABB", "SMULWT", "SMMULR", "UMAAL", "CLZ", "RBIT", "REV", "REV16", "SXTB", "UXTAB16",
    "BFI", "BFC", "UBFX", "SBFX", "QADD", "QDSUB", "SADD16", "UQSUB8", "SHASX", "UHSAX",
    "SEL", "SSAT", "USAT16", "PKHBT", "MRS", "MSR", "MRC", "MCR", "MRC2", "MCRR", "CDP",
    "LDC", "LDCL", "LDCEQL", "STC2L", "BKPT", "CLREX", "DMB", "DSB", "ISB", "PLD", "PLI",
    "CPSIE", "CPSID", "SETEND", "RFEIA", "SRSDB", "WFI", "WFE", "SEV", "YIELD", "DBG",
    "SMC", "IT", "ITTE", "ITETT", "BUL", "ADDULS",
    "VADD.F32", "vaddeq.f32", "VSUB.F64", "VMUL.F32", "VDIV.F64", "VSQRT.F32", "VABS.F64",
    "VNEG.F32", "VMLA.F32", "VNMUL.F64", "VCMP.F32", "VCMPE.F64", "VCVT.F32.S32",
    "VCVT.S32.F64", "VCVTR.S32.F32", "VCVTB.F16.F32", "VMOV", "VMOV.F32", "VMOV.32",
    "VMOVEQ", "VMRS", "VMSR", "VLDR", "VSTR", "VLDM", "VLDMIA", "VSTMDB", "VPUSH", "VPOP",
    "VPUSH.64", "VADD.I32", "VADDQ", "VADDQ.I8", "VLD1.32", "VST4.8", "VDUP.32",
    "VMOVL.S16", "VMULL.U8", "VEXT.8", "VZIP.16", "VTBL.8", "VQADD.S8", "VSHR.U32",
    "VRSQRTE.F32", "VCVT.F16.F32", "FADDS", "FADDD", "FMRX", "FLDMIAS", "FMSTAT",
    "LDR.W", "ADDS.N", "B.W",
    "LDRHT", "LDREQHT", "LDRHTEQ", "LDRNESBT", "LDRSHTNE", "STREQHT", "LDSB", "LDSEQB",
    "LDSHEQ", "VDUPQ.32", "VDUPQEQ.32", "UDF", "UDFEQ", "VADD.F", "VCVT.S32.F", "VADD.D",
])
def test_recognised_mnemonics(word):
    assert is_mnemonic(word)
    assert pieces(word + " R0")[0] == (MNEMONIC, word)


@pytest.mark.parametrize("word", [
    "FOO", "ADDD", "ADDSS", "ADDQQ", "MOVEQQ", "ADDEQEQ", "LDREQBB", "PLDEQ", "BKPTEQ",
    "DMBEQ", "CPSIEEQ", "VLD1EQ", "VADDLEQ", "ADD.F32", "LDR.I32", "VADD.X32",
    "VADD.F32.F32.F32", "VADD.W.F32", "ADD.", "B.", "PRINT_CHAR", "R0", "ASL", "LDRBB",
    "SDIV", "UDIV", "VFMA", "CBZ", "ORN", "MOV32", "LDMIAFD", "EQ", "S", "",
    "VQRDMLAH", "LDS", "LDSEQ", "VADDQEQ", "VADD.I", "VADD.S",
])
def test_not_mnemonics(word):
    assert not is_mnemonic(word)


def test_mnemonic_base():
    assert mnemonic_base("addeqs") == "ADD"
    assert mnemonic_base("LDRNEB") == "LDR"
    assert mnemonic_base("STMEQFD") == "STM"
    assert mnemonic_base("ldreqsbt") == "LDR"
    assert mnemonic_base("LDSEQH") == "LDS"
    assert mnemonic_base("VADDQ.I16") == "VADD"
    assert mnemonic_base("ITTE") == "IT"
    assert mnemonic_base("foo") is None


# Agreement with the bundled assembler and with Capstone --------------------

# The assembler knows these mnemonics without operands but rejects them on the
# Cortex-A9 once operands are given: ARMv8.1 rounding multiply-accumulate and
# an M-profile vector move.
NOT_ON_CORTEX_A9 = {"VQRDMLAH", "VQRDMLAHQ", "VQRDMLSH", "VQRDMLSHQ", "VMOVLB"}


def assembler_errors(workdir, lines, syntax):
    """The first error of each line (or None) when assembled in the given syntax."""
    source = workdir / f"{syntax}.s"
    source.write_text(f"\t.syntax {syntax}\n" + "".join(f"\t{line}\n" for line in lines),
                      encoding="utf-8", newline="\n")
    proc = subprocess.run(
        [str(tool_path(ASSEMBLER)), *AS_OPTIONS, "-o", f"{syntax}.o", source.name],
        cwd=workdir, capture_output=True, text=True, timeout=120,
        env=dict(os.environ, LC_ALL="C", LANG="C"))
    errors = [None] * len(lines)
    for message in parse_assembler_output(proc.stderr):
        index = (message.line or 0) - 2
        if message.severity == ERROR and 0 <= index < len(lines) and errors[index] is None:
            errors[index] = message.text
    return errors


def unknown_to_assembler(workdir, words):
    """Words that both syntaxes reject as an instruction this processor has."""
    def rejects(error):
        return error is not None and (
            error.startswith("bad instruction")
            or error.startswith("selected processor does not support `"))
    divided = assembler_errors(workdir, words, "divided")
    unified = assembler_errors(workdir, words, "unified")
    return {w for w, d, u in zip(words, divided, unified) if rejects(d) and rejects(u)}


def test_assembler_knows_every_recognised_form(tmp_path):
    forms = mnemonic_forms()
    assert len(forms) > 8000
    samples = forms + [f + ".W" for f in forms] + [f + ".F32.S32" for f in forms if f[0] == "V"]
    assert all(is_mnemonic(s) for s in samples)
    divided = assembler_errors(tmp_path, samples, "divided")
    unified = assembler_errors(tmp_path, samples, "unified")
    assert divided[0] == "ARM register expected -- `adc'"   # the probe really ran
    bad = [s for s, d, u in zip(samples, divided, unified)
           if (d or "").startswith("bad instruction") and (u or "").startswith("bad instruction")]
    assert bad == []


def test_rejected_forms_are_bad_instructions(tmp_path):
    words = ["ADDSEQS", "LDREQBB", "FOO", "ADDD", "LDMEQIAFD", "VLDMEQIA", "FADDEQS"]
    assert unknown_to_assembler(tmp_path, words) == set(words)
    assert not any(is_mnemonic(w) for w in words)


@pytest.mark.skipif(sys.platform != "win32", reason="elsewhere the program file shares the ends "
                                                    "of its strings, so the words cannot be read")
def test_every_assembler_instruction_is_recognised(tmp_path):
    # The assembler's own instruction table, read from the strings in its program file.
    data = tool_path(ASSEMBLER).read_bytes()
    words = sorted({m.group().decode() for m in
                    re.finditer(rb"(?<=\x00)[a-z][a-z0-9]{1,11}(?=\x00)", data)})
    unknown = unknown_to_assembler(tmp_path, words)
    known = [w for w in words if w not in unknown]
    assert {"add", "ldr", "push", "svc", "vadd", "vld1", "fadds", "smullals"} <= set(known)
    missing = [w for w in known if not is_mnemonic(w) and w.upper() not in NOT_ON_CORTEX_A9]
    assert missing == []


def test_every_capstone_instruction_is_recognised(tmp_path):
    names = sorted(n[len("ARM_INS_"):] for n in dir(arm_const)
                   if n.startswith("ARM_INS_") and n not in ("ARM_INS_INVALID", "ARM_INS_ENDING"))
    unknown = unknown_to_assembler(tmp_path, names)
    known = [n for n in names if n not in unknown]
    assert len(known) > 350
    missing = [n for n in known if not is_mnemonic(n) and n not in NOT_ON_CORTEX_A9]
    assert missing == []


def test_exceptions_are_rejected_with_operands(tmp_path):
    lines = ["VQRDMLAH.S16 D0, D1, D2", "VQRDMLAHQ.S16 Q0, Q1, Q2",
             "VQRDMLSH.S16 D0, D1, D2", "VQRDMLSHQ.S16 Q0, Q1, Q2", "VMOVLB.S8 Q0, Q1"]
    assert all(assembler_errors(tmp_path, lines, "unified"))


# Without operands the assembler stops at the missing operands before it sees
# that these cannot take a condition, or that the processor lacks them (an
# M-profile VMULLT). VMOVLTEQ is read as VMOVLT, and the EQ is dropped.
NOT_CONDITIONAL_WITH_OPERANDS = re.compile(
    r"(?:IT[TE]{0,3}|CPS(?:IE|ID)?|SETEND|SRS(?:[DI][AB]|[EF][AD])?|VMOVQ|VMULLT|VMOVLT)EQ")


def test_every_assembler_form_with_a_condition_or_s_is_recognised(tmp_path):
    # A condition or an S put at every place of every recognised form that has
    # no condition yet (ADDEQ is ADD with EQ, but TEQ has none).
    forms = set(mnemonic_forms())
    plain = [form for form in forms
             if not any(form[i:i + 2] in CONDITIONS and form[:i] + form[i + 2:] in forms
                        for i in range(1, len(form) - 1))]
    assert {"ADD", "ADDS", "TEQ", "SMLAL", "LDRSBT", "VDUPQ"} <= set(plain)
    assert not {"ADDEQ", "ADDSEQ", "ADDEQS", "BLS", "LDREQB"} & set(plain)
    variants = {form[:i] + extra + form[i:] for form in plain
                for i in range(1, len(form) + 1) for extra in ("EQ", "S")}
    variants = sorted(v for v in variants if not is_mnemonic(v))
    divided = assembler_errors(tmp_path, variants, "divided")
    unified = assembler_errors(tmp_path, variants, "unified")

    def rejects(error):
        return error is not None and error.startswith((
            "bad instruction", "instruction cannot be conditional",
            "selected processor does not support"))
    accepted = [v for v, d, u in zip(variants, divided, unified)
                if not (rejects(d) and rejects(u))]
    assert "ITEQ" in accepted               # the probe really ran
    assert [v for v in accepted if not NOT_CONDITIONAL_WITH_OPERANDS.fullmatch(v)] == []


def test_condition_exceptions_are_rejected_with_operands(tmp_path):
    lines = ["ITEQ EQ", "ITTEEQ EQ", "CPSEQ #16", "CPSIDEQ I", "SETENDEQ BE",
             "SRSDBEQ SP!, #16", "VMOVQEQ Q0, Q1", "VMULLTEQ.S16 Q0, D1, D2"]
    for syntax in ("divided", "unified"):
        assert all(assembler_errors(tmp_path, lines, syntax))


# Speed ---------------------------------------------------------------------

@pytest.mark.serial
def test_tokenize_line_is_fast():
    lines = MIXED.read_text(encoding="utf-8").split("\n")
    text = "\n".join((lines * (2000 // len(lines) + 1))[:2000])
    start = time.perf_counter()
    for _ in range(5):
        tokenize(text)
    per_line = (time.perf_counter() - start) / (5 * 2000)
    assert per_line < 0.0002        # 0.2 ms; about 0.015 ms on a typical PC
