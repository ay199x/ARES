# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARM formats and classes as DynARMic classifies them, and its counts for the test programs.

tests/data/dynarmic holds, for each test program, DynARMic's own rules
applied to every instruction ARES completes when it runs the program (with
its .in input): the expected counts were made once with DynARMic's code.
ARES must give the same counts, counting per basic block.
"""

import json
import struct
from collections import Counter

import pytest
from conftest import PROGRAMS, ROOT

from ares import classify
from ares.classify import CLASSES, FORMATS
from ares.gui.tools import counter
from ares.machine import Machine
from ares.runner import Runner, State

EXPECTED = ROOT / "tests" / "data" / "dynarmic"
# The benchmark's file is checked with the counter connected (test_benchmark.py).
CASES = sorted(path for path in EXPECTED.glob("*.json") if path.stem != "loop10m")


def words(build, *lines):
    """The words of instructions, assembled after _start."""
    program = build(".global _start\n_start:\n" + "".join(f"        {line}\n" for line in lines))
    section = next(s for s in program.sections if s.executable)
    return [word for (word,) in struct.iter_unpack("<I", section.data[:4 * len(lines)])]


@pytest.mark.parametrize("line, kind, group", [
    ("ADD R0, R1, R2", "fmt_dp_reg", "alu"),
    ("MOV R4, R0", "fmt_dp_reg", "alu"),
    ("LSL R0, R0, R1", "fmt_dp_reg", "alu"),
    ("ADD R0, R0, #1", "fmt_dp_imm", "alu"),
    ("ADD R4, R0, R0, LSL #1", "fmt_dp_imm", "alu"),
    ("CMP R0, #10", "fmt_dp_imm", "alu"),
    ("BIC R0, R0, #1", "fmt_dp_imm", "alu"),
    ("LDR R0, [R1]", "fmt_ls_imm", "reg_transfer"),
    ("STR R0, [R1, #4]", "fmt_ls_imm", "reg_transfer"),
    ("LDR R0, [R1, R9]", "fmt_ls_imm", "reg_transfer"),     # R9 is "sb" for Capstone
    ("LDR R0, [R1, R12]", "fmt_ls_imm", "reg_transfer"),    # R12 is "ip"
    ("LDR R0, [R1, SP]", "fmt_ls_imm", "reg_transfer"),
    ("LDR R0, [R1, LR]", "fmt_ls_imm", "reg_transfer"),
    ("LDR R0, [R1, R8]", "fmt_ls_reg", "reg_transfer"),
    ("LDR R0, [R1], R2", "fmt_ls_imm", "reg_transfer"),
    ("LDRH R0, [R1, #2]", "fmt_ls_imm", "reg_transfer"),
    ("LDR R0, [R1, R2]", "fmt_ls_reg", "reg_transfer"),
    ("STR R0, [R1, R2, LSL #2]", "fmt_ls_reg", "reg_transfer"),
    ("LDR R0, [R1, -R2]", "fmt_ls_reg", "reg_transfer"),
    ("LDRB R0, [R1]", "fmt_ls_imm", "memory"),
    ("STRB R0, [R1, R2]", "fmt_ls_reg", "memory"),
    ("LDRSB R0, [R1]", "fmt_ls_imm", "memory"),
    ("LDRNE R0, [R1]", "fmt_ls_imm", "cond_load_other"),
    ("LDRNEB R0, [R1]", "fmt_ls_imm", "cond_load_other"),
    ("STREQ R0, [R1, R2]", "fmt_ls_reg", "cond_load_other"),
    ("B _start", "fmt_branch", "branch"),
    ("BNE _start", "fmt_branch", "branch"),
    ("BL _start", "fmt_branch", "branch"),
    ("BX LR", "fmt_branch", "branch"),
    ("BLX R3", "fmt_branch", "branch"),
    ("MUL R0, R1, R2", "fmt_mul", "alu"),
    ("MLA R0, R1, R2, R3", "fmt_mul", "alu"),
    ("UMULL R0, R1, R2, R3", "fmt_mul", "alu"),
    ("PUSH {R4, LR}", "fmt_lsm", "reg_transfer"),
    ("POP {R4, PC}", "fmt_lsm", "reg_transfer"),
    ("LDM R1, {R2, R3}", "fmt_lsm", "reg_transfer"),
    ("STMDB R1!, {R2, R3}", "fmt_lsm", "alu"),             # "stmdb": no rule of its own
    ("SVC #1", "fmt_svc", "cond_load_other"),
    ("NOP", "fmt_dp_reg", "alu"),
    ("VMUL.F32 S0, S0, S1", "fmt_dp_reg", "alu"),
    ("VLDR D1, [R1, #8]", "fmt_dp_imm", "alu"),
])
def test_formats_and_classes(build, line, kind, group):
    (word,) = words(build, line)
    assert classify.classify(word) == (FORMATS.index(kind), CLASSES.index(group))


def test_dynarmic_is_credited_in_the_words_of_the_tools_help():
    """Here as in the Help of the Dynamic Instruction Counter, which counts with its rules."""
    for text in (classify.__doc__, counter.HELP):
        text = " ".join(text.split())
        assert "DynARMic (GLSVLSI 2026), a dynamic ARM instruction counting tool" in text
        assert "with its author's permission" in text


def test_a_word_capstone_cannot_decode():
    """Both of DynARMic's rules fall through to their last answer."""
    assert classify.classify(0xFFFFFFFF) == (FORMATS.index("fmt_dp_reg"), CLASSES.index("alu"))


def test_tally(build):
    data = b"".join(struct.pack("<I", word) for word in words(
        build, "ADD R0, R0, #1", "ADD R0, R0, #1", "LDRB R0, [R1]", "SVC #10"))
    formats, classes = classify.tally(data + b"\x01\x02")        # a part word is no instruction
    assert dict(zip(FORMATS, formats)) == {**dict.fromkeys(FORMATS, 0), "fmt_dp_imm": 2,
                                           "fmt_ls_imm": 1, "fmt_svc": 1}
    assert dict(zip(CLASSES, classes)) == {**dict.fromkeys(CLASSES, 0), "alu": 2, "memory": 1,
                                           "cond_load_other": 1}


def counts_by_blocks(build, source):
    """(instructions, formats, classes) of a run of a program, counted per basic block."""
    machine = Machine(build(source.read_text()))
    typed = source.with_suffix(".in")
    if typed.is_file():
        machine.console.feed(typed.read_text())
    machine.console.close_input()
    blocks = machine.observers.count_blocks("test")
    assert Runner(machine).run() is State.FINISHED and machine.error is None
    formats, classes = Counter(), Counter()
    for (address, size), count in blocks.runs.items():
        kinds, groups = classify.tally(machine.read_memory(address, size))
        for name, number in zip(FORMATS, kinds):
            formats[name] += count * number
        for name, number in zip(CLASSES, groups):
            classes[name] += count * number
    return blocks.instructions(), formats, classes


def test_every_test_program_has_its_expected_counts():
    programs = {p.stem for p in PROGRAMS.glob("*.s") if p.with_suffix(".out").is_file()}
    assert programs == {path.stem for path in EXPECTED.glob("*.json")}
    assert "formats" in programs


@pytest.mark.parametrize("expected", CASES, ids=lambda path: path.stem)
def test_counts_equal_dynarmic(build, expected):
    record = json.loads(expected.read_text())
    instructions, formats, classes = counts_by_blocks(build, PROGRAMS / record["program"])
    assert instructions == record["instructions"]
    assert {name: formats[name] for name in FORMATS} == record["formats"]
    assert {name: classes[name] for name in CLASSES} == record["classes"]


def test_the_format_program_has_every_format_and_class():
    record = json.loads((EXPECTED / "formats.json").read_text())
    assert all(record["formats"].values()) and all(record["classes"].values())
