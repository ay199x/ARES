# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Help window's instruction lists: they say only what ARES really assembles."""

import re

import pytest

from ares import instructions, tokens
from ares.assembler import assemble
from ares.capitals import offences
from ares.instructions import BASIC, CONDITIONS, EXTENDED, LEFT_OUT, Row, variants

ROWS = BASIC + EXTENDED


def every_line():
    """Every example line of the lists, the rows of the groups too."""
    lines = []
    for row in ROWS:
        lines.append(row.example)
        lines += [member.example for member in variants(row)]
    return lines


def program(lines):
    """A program with the lines. Each has a label of its own right after it, because some reach
    only a few hundred bytes, and a literal pool where it needs one."""
    source = ["        .global _start", "        .text", "_start: NOP"]
    for number, line in enumerate(lines):
        source.append("        " + re.sub(r"\blabel\b", f"label_{number}", line))
        source.append(f"label_{number}: NOP")
        if "=" in line:
            source.append("        .ltorg")
    return "\n".join(source) + "\n"


@pytest.fixture(scope="module")
def assembled(tmp_path_factory):
    """(source lines, result) of the one program with every example line."""
    source = program(every_line())
    return source.split("\n"), assemble(source, tmp_path_factory.mktemp("lists"))


def test_every_example_line_assembles_with_the_real_assembler(assembled):
    lines, result = assembled
    assert result.ok, [(m.text, lines[m.line - 1]) for m in result.errors][:20]


def test_no_example_line_has_a_warning(assembled):
    lines, result = assembled
    assert [(m.text, lines[m.line - 1]) for m in result.messages] == []


def test_every_example_line_keeps_the_rule_of_capitals():
    assert offences(program(every_line())) == []


def test_lowercase_lines_would_be_refused():
    # The rule looks at these lines: a list of symbols would pass it unread.
    assert offences("    add r1, r2, r3\n    vadd.f32 s1, s2, s3\n")


@pytest.mark.parametrize("name, rows", [("Basic", BASIC), ("Extended", EXTENDED)])
def test_a_list_is_sorted_with_no_row_twice(name, rows):
    examples = [row.example for row in rows]
    assert examples == sorted(examples) and len(set(examples)) == len(examples)


def test_an_instruction_is_on_one_of_the_lists_or_left_out_for_a_reason():
    on_lists = instructions.listed_bases()
    left_out = instructions.left_out_names()
    assert instructions.token_bases() - on_lists - left_out == set()
    assert on_lists & left_out == set()


def test_what_is_left_out_is_named_in_the_tokens_with_a_reason():
    assert instructions.left_out_names() <= instructions.token_bases()
    for names, why in LEFT_OUT:
        assert names and len(why) > 20
    assert len(instructions.left_out_names()) < len(instructions.token_bases()) / 3


def test_every_mnemonic_on_the_lists_is_one_the_highlighting_knows():
    for line in every_line():
        assert tokens.is_mnemonic(line.split()[0]), line


@pytest.mark.parametrize("line", [
    "LDR R1, =100000", "LDR R1, =label", "ADR R1, label", "PUSH {R1, R2}", "POP {R1, R2}", "NOP",
    "LSL R1, R2, #2", "LSR R1, R2, #2", "ASR R1, R2, #2", "ROR R1, R2, #8", "RRX R1, R2",
    "NEG R1, R2"])
def test_the_common_pseudo_instructions_are_on_the_extended_list(line):
    assert line in [row.example for row in EXTENDED]
    assert line not in [row.example for row in BASIC]


@pytest.mark.parametrize("word", [
    "MOV", "ADD", "LDR", "STR", "LDRB", "LDM", "STM", "B", "BL", "BX", "MUL", "SMULL", "BFI",
    "SSAT", "QADD", "UADD8", "SEV", "DMB", "SVC", "MRS", "VADD.F32", "VLDR", "VADD.I32", "VLD1.32"])
def test_each_kind_of_instruction_is_on_the_basic_list(word):
    assert word in {row.word for row in BASIC}


def test_loads_and_stores_show_every_addressing_mode():
    operands = {row.example.split(" ", 1)[1] for row in BASIC if row.word == "LDR"}
    assert {"R1, [R2]", "R1, [R2, #100]", "R1, [R2, R3]", "R1, [R2, R3, LSL #2]", "R1, [R2, #100]!",
            "R1, [R2], #100", "R1, [R2], R3", "R1, label"} <= operands


def row(example):
    return next(row for row in ROWS if row.example == example)


def test_a_group_has_the_conditions_and_then_the_s_form():
    group = [member.example for member in variants(row("MOV R1, R2"))]
    assert group == [f"MOV{code} R1, R2" for code, words, flags in CONDITIONS] + ["MOVS R1, R2"]


def test_the_group_of_mov_has_its_conditions_and_s_form():
    group = {member.example.split()[0] for member in variants(row("MOV R1, R2"))}
    assert {"MOVEQ", "MOVNE", "MOVGT", "MOVLT", "MOVS"} <= group


def test_a_condition_goes_before_an_ending_as_the_assembler_wants():
    assert "LDREQB R1, [R2]" in [member.example for member in variants(row("LDRB R1, [R2]"))]
    assert "LDMEQIA R1, {R2, R3}" in [member.example
                                      for member in variants(row("LDMIA R1, {R2, R3}"))]


def test_a_type_stays_after_the_condition():
    assert "VADDEQ.F32 S1, S2, S3" in [member.example
                                       for member in variants(row("VADD.F32 S1, S2, S3"))]


@pytest.mark.parametrize("example", ["VADD.I32 D0, D1, D2", "BKPT #1", "BLX label", "CLREX",
                                     "UDF #1", "VLD1.32 {D0, D1}, [R1]"])
def test_what_takes_no_condition_has_no_group(example):
    assert variants(row(example)) == ()


def test_a_row_knows_it_has_a_group_without_making_it():
    for item in ROWS:
        assert instructions.has_variants(item) == bool(variants(item)), item


def test_a_comparison_has_no_s_form_because_it_always_sets_the_flags():
    assert [member.example for member in variants(row("CMP R1, R2"))
            if member.word.startswith("CMPS")] == []


def test_a_row_of_a_group_says_when_it_runs():
    member = variants(row("MOV R1, R2"))[0]
    assert member == Row("MOVEQ R1, R2", "As MOV, if equal (Z set)", False)
    assert variants(row("MUL R1, R2, R3"))[-1].description == "As MUL, and sets N and Z"
    assert variants(row("ADD R1, R2, R3"))[-1].description == "As ADD, and sets N, Z, C and V"


def test_the_condition_codes_are_those_of_the_tokens():
    assert {code for code, words, flags in CONDITIONS} == set(tokens.CONDITIONS) - {"UL"}


def test_a_row_is_its_example_padded_to_the_column_then_its_description():
    example = row("MOV R1, R2")
    width = instructions.column(BASIC)
    text = instructions.text_of(example, width, instructions.CLOSED)
    assert text.startswith("+ MOV R1, R2 ")
    assert text[width:] == example.description


def test_the_column_leaves_room_for_every_example_of_a_list():
    for rows in (BASIC, EXTENDED):
        width = instructions.column(rows)
        examples = [member.example for item in rows for member in variants(item)]
        examples += [item.example for item in rows]
        assert max(len(instructions.VARIANT + example) for example in examples) < width


def test_a_row_fits_the_window_without_going_sideways():
    # 104 characters of the font of programs fit the list at the window's usual size.
    for rows in (BASIC, EXTENDED):
        width = instructions.column(rows)
        for item in rows:
            assert width + len(item.description) <= 104, item


@pytest.mark.parametrize("line", [
    "ADDEQS R1, R2, R3", "ADDUL R1, R2, R3", "CMPP R1, R2", "VADDQ.I32 Q0, Q1, Q2"])
def test_the_forms_the_lists_do_not_show_are_true(line, tmp_path):
    assert assemble(program([line]), tmp_path).ok


def test_the_order_of_unified_syntax_is_as_the_limits_say(tmp_path):
    source = "        .syntax unified\n" + program(["LDRBEQ R1, [R2]", "LDMIAEQ R1, {R2, R3}"])
    assert assemble(source, tmp_path).ok
    assert not assemble(program(["LDRBEQ R1, [R2]"]), tmp_path).ok


def test_a_row_on_q_registers_says_q_in_its_description():
    rows = {row.example: row.description for row in instructions.BASIC}
    assert "Q1" in rows["VABA.S32 Q0, Q1, Q2"] and "D1" not in rows["VABA.S32 Q0, Q1, Q2"]


def test_a_lane_keeps_its_d_register_in_a_row_on_q_registers():
    rows = [row for row in instructions.BASIC if row.example.startswith("VMUL.I32 Q0")
            and "[" in row.example]
    assert rows and all("D2" in row.description for row in rows)


@pytest.mark.parametrize("example", ["VMOV.32 D0[1], R1", "VMOV.32 R1, D0[1]", "VDUP.32 D0, R1",
                                     "VDUP.32 Q0, R1"])
def test_core_register_moves_have_conditions(example):
    row = next(row for row in instructions.BASIC if row.example == example)
    assert instructions.has_variants(row)
