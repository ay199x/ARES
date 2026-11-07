# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Dynamic Instruction Counter's model: one connection counts the categories and the
encoding formats, and what survives Assemble and Reset; its percentages, rounded as
DynARMic's page rounds them; its Help, whose examples count where it says; and that nothing
of it is about cycles."""

import importlib.util
import json
import re
import struct
from fractions import Fraction
from pathlib import Path

import pytest
from conftest import PROGRAMS, ROOT
from test_observers import READ_INT, Reference

from ares.classify import CLASSES, FORMATS, classify
from ares.gui.tools import counter
from ares.gui.tools.counter import (CATEGORY_PANEL, FORMAT_PANEL, HELP, CounterModel,
                                    percentage, share)
from ares.gui.tools.frame import paragraphs
from ares.machine import Machine, StopReason
from ares.runner import Runner, State

# DynARMic's counts for the test programs (see test_classify.py).
EXPECTED = ROOT / "tests" / "data" / "dynarmic"
CASES = sorted(path for path in EXPECTED.glob("*.json") if path.stem != "loop10m")

COUNT = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
        MOV     R0, #0
loop:   ADD     R0, R0, #1
        STRB    R0, [R1]
        CMP     R0, #3
        BNE     loop
        PUSH    {R0, R1}
        POP     {R0, R1}
        STR     R0, [R1]
        LDREQ   R2, [R1]
        SVC     #10
"""
# LDR, MOV, then 3 x (ADD, STRB, CMP, BNE), PUSH, POP, STR, LDREQ, SVC
TOTAL = 2 + 3 * 4 + 5
COUNT_CLASSES = {"alu": 1 + 3 * 2, "branch": 3, "memory": 3, "reg_transfer": 4,
                 "cond_load_other": 2}
COUNT_FORMATS = {**dict.fromkeys(FORMATS, 0), "fmt_dp_imm": 7, "fmt_ls_imm": 6,
                 "fmt_branch": 3, "fmt_lsm": 2, "fmt_svc": 1}


def classes(model):
    return dict(zip(CLASSES, model.classes))


def formats(model):
    return dict(zip(FORMATS, model.formats))


def make(build, source=COUNT):
    machine = Machine(build(source))
    return machine, Runner(machine)


# Counting -------------------------------------------------------------------------------

def test_one_connection_counts_the_categories_and_the_formats(build):
    machine, runner = make(build)
    hooks = len(machine.uc._callbacks)
    model = CounterModel()
    model.connect(machine)
    assert model.connected and model.machine is machine
    assert machine.observers._counting == [model]               # one connection
    assert len(machine.uc._callbacks) == hooks + 1              # one block hook
    assert runner.run() is State.FINISHED
    assert model.update() and not model.update()                # nothing new the second time
    assert model.total == TOTAL == sum(model.classes) == sum(model.formats)
    assert classes(model) == COUNT_CLASSES
    assert formats(model) == COUNT_FORMATS


@pytest.mark.parametrize("how", ["go", "step"])
@pytest.mark.parametrize("expected", CASES, ids=lambda path: path.stem)
def test_it_gives_dynarmics_counts(build, expected, how):
    """Both panels' counts, through one connection. Whole runs, and runs stopped after every
    instruction, taken in now and then: each step completes one instruction of these
    programs (until the last)."""
    record = json.loads(expected.read_text())
    source = PROGRAMS / record["program"]
    machine = Machine(build(source.read_text()))
    typed = source.with_suffix(".in")
    if typed.is_file():
        machine.console.feed(typed.read_text())
    machine.console.close_input()
    runner = Runner(machine)
    model = CounterModel()
    model.connect(machine)
    if how == "go":
        assert runner.run() is State.FINISHED
    else:
        steps = 0
        while runner.step() is not State.FINISHED:
            steps += 1
            if steps % 3 == 0:
                model.update()
                assert model.total == steps
    model.update()
    assert machine.error is None
    assert model.total == record["instructions"]
    assert formats(model) == record["formats"]
    assert classes(model) == record["classes"]


def every_instruction(machine, reference):
    """(formats, classes) that a counter seeing every instruction counted."""
    kinds, groups = dict.fromkeys(FORMATS, 0), dict.fromkeys(CLASSES, 0)
    for address, runs in reference.counts.items():
        (word,) = struct.unpack("<I", machine.read_memory(address, 4))
        kind, group = classify(word)
        kinds[FORMATS[kind]] += runs
        groups[CLASSES[group]] += runs
    return kinds, groups


# Three instructions: the chunks of a run (10,000 instructions) end inside the loop.
SPINS = """\
        .global _start
_start: ADD     R0, R0, #1
        STRB    R0, [SP, #-1]
        B       _start
"""
FAILS = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
        STRB    R0, [R1]
        SVC     #99
"""


@pytest.mark.parametrize("how", ["breakpoint", "pause", "waiting", "error"])
def test_runs_stopped_inside_a_block_count_each_instruction_once(build, how):
    """A breakpoint, Pause, a system call that waits for input and a runtime error stop runs
    inside a block: both panels count as a counter that sees every instruction."""
    source = {"breakpoint": COUNT, "pause": SPINS, "waiting": READ_INT, "error": FAILS}[how]
    machine, runner = make(build, source)
    model = CounterModel()
    model.connect(machine)
    reference = Reference(machine)

    def same():
        model.update()
        assert (formats(model), classes(model)) == every_instruction(machine, reference)
        assert model.total == sum(reference.counts.values()) > 0
    if how == "breakpoint":
        runner.set_breakpoint(machine.program.label_address("loop") + 4)     # STRB
        for _ in range(3):
            assert runner.run() is State.PAUSED
            same()
    elif how == "pause":
        for _ in range(3):
            runner.go()
            runner.run_slice()
            runner.pause()
            assert runner.run_slice() is State.PAUSED
            same()
        return
    elif how == "waiting":
        assert runner.run() is State.WAITING
        same()
        machine.console.feed("41\n")
    assert runner.run() is State.FINISHED
    assert (machine.stop_reason is StopReason.ERROR) is (how == "error")
    same()


def test_nothing_is_counted_while_disconnected(build):
    machine, runner = make(build)
    model = CounterModel()
    model.observe(machine)                  # not connected: the program is not observed
    assert model.machine is None and not machine.observers.active
    runner.step()
    model.connect(machine)
    runner.step()
    runner.step()
    model.disconnect()
    assert not machine.observers.active and model.total == 2
    assert classes(model) == {**dict.fromkeys(CLASSES, 0), "alu": 2}          # MOV, ADD
    assert formats(model) == {**dict.fromkeys(FORMATS, 0), "fmt_dp_imm": 2}
    runner.step()
    assert not model.update() and model.total == 2
    model.connect(machine)
    runner.run()
    model.update()
    assert model.total == TOTAL - 2          # the two steps while disconnected


def test_it_keeps_counting_across_reset_backstep_and_assemble(build):
    machine, runner = make(build)
    model = CounterModel()
    model.connect(machine)
    for _ in range(4):
        runner.step()
    runner.backstep()                       # undone, but it was executed
    model.update()
    assert model.total == 4
    runner.step()
    runner.reset()
    runner.run()
    model.update()
    assert model.total == 5 + TOTAL
    other, other_runner = make(build)       # a new Assemble: the window passes the new machine
    model.observe(other)
    assert not machine.observers.active and model.machine is other
    other_runner.run()
    model.update()
    assert model.total == 5 + 2 * TOTAL == sum(model.classes) == sum(model.formats)
    model.observe(None)                     # the program's file closed: still connected
    assert model.connected and not other.observers.active
    assert model.total == 5 + 2 * TOTAL


def test_reset_starts_again_from_zero(build):
    machine, runner = make(build)
    model = CounterModel()
    model.connect(machine)
    runner.step()
    runner.step()
    model.reset()                           # also what ran since the last update
    assert model.total == 0
    assert model.formats == [0] * len(FORMATS) and model.classes == [0] * len(CLASSES)
    runner.run()
    model.update()
    assert model.total == TOTAL - 2 == sum(model.classes) == sum(model.formats)


def test_connected_without_a_program_it_counts_the_next_one(build):
    model = CounterModel()
    model.connect(None)
    assert model.connected and model.machine is None and not model.update()
    machine, runner = make(build)
    model.observe(machine)
    runner.run()
    model.update()
    assert model.total == TOTAL and classes(model) == COUNT_CLASSES


def test_two_counters_share_the_counting_with_their_own_baselines(build):
    machine, runner = make(build)
    first, second = CounterModel(), CounterModel()
    first.connect(machine)
    hooks = len(machine.uc._callbacks)
    runner.step()
    runner.step()
    second.connect(machine)
    assert len(machine.uc._callbacks) == hooks              # the same block hook
    runner.run()
    first.update()
    second.update()
    assert (first.total, second.total) == (TOTAL, TOTAL - 2)
    first.disconnect()
    assert machine.observers.active
    second.disconnect()
    assert not machine.observers.active


def test_bkpt_ends_the_program_and_is_never_counted(build):
    """Of Conditional Load & Others and of Supervisor Call & Others, but a runtime error in
    ARES (the Help)."""
    machine, runner = make(build, ".global _start\n_start: MOV R0, #1\n        BKPT #0\n")
    model = CounterModel()
    model.connect(machine)
    assert runner.run() is State.FINISHED and machine.stop_reason is StopReason.ERROR
    model.update()
    assert model.total == 1 and classes(model) == {**dict.fromkeys(CLASSES, 0), "alu": 1}
    assert formats(model) == {**dict.fromkeys(FORMATS, 0), "fmt_dp_imm": 1}


# Ten million instructions with the counter connected: test_benchmark.py.

def load_benchmark():
    """tools/benchmark.py, a script, as a module."""
    found = importlib.util.spec_from_file_location("benchmark_script",
                                                   ROOT / "tools" / "benchmark.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def test_the_benchmark_connects_the_counter(capsys):
    benchmark = load_benchmark()
    assert "counter" in benchmark.tool_names() and "statistics" not in benchmark.tool_names()
    assert benchmark.main(["--repeat", "1", "--tool", "counter"]) == 0
    printed = capsys.readouterr().out
    assert "with the Dynamic Instruction Counter connected" in printed
    assert "the tool counted 10,000,009 instructions" in printed


# The percentages --------------------------------------------------------------------------

@pytest.mark.parametrize("part, whole, text", [
    (0, 0, "0.0%"), (0, 7, "0.0%"), (5, 5, "100.0%"), (2, 3, "66.7%"), (1, 3, "33.3%"),
    (1, 8, "12.5%"),
    (1, 16, "6.3%"), (3, 48, "6.3%"), (49, 400, "12.3%"), (15, 16, "93.8%"),  # ties: up
    (11, 80, "13.8%"), (7, 400, "1.8%"),        # the double lies just above a tie
    (23, 80, "28.7%"), (41, 80, "51.2%"),       # the double lies just under a tie
    (1, 2000, "0.1%"), (1, 2001, "0.0%"), (7, 10_000_016, "0.0%"),
    (10_000_009, 10_000_016, "100.0%"),
])
def test_percentages_are_rounded_as_dynarmics_page_rounds_them(part, whole, text):
    """JavaScript's ((part / whole) * 100).toFixed(1): the double rounded half up on its exact
    binary value. 23 of 80 is exactly 28.75 %, but the double is 28.749999999999996."""
    assert percentage(share(part, whole)) == text


def test_a_double_just_under_a_tie_rounds_down():
    """Where exact arithmetic would round up, as the frame's percentage bar does."""
    assert Fraction(23 * 100, 80) == Fraction(2875, 100) and 23 / 80 * 100 < 28.75
    assert share(23, 80) == 287 and share(11, 80) == 138 and share(49, 400) == 123


# The Help -------------------------------------------------------------------------------

def panel_help(panel):
    """{label: paragraph} of the Help's part about a panel: the paragraphs after the one that
    names the panel, up to the first that starts with none of its labels."""
    title, labels = panel
    side = "left" if panel is CATEGORY_PANEL else "right"
    parts = paragraphs(HELP).split("\n\n")
    found = {}
    for part in parts[parts.index(f"{title}, the {side} panel:") + 1:]:
        label = next((label for label in labels if part.startswith(label + " ")), None)
        if label is None:
            break
        found[label] = part
    return found


def test_the_help_has_a_paragraph_for_each_category_and_format_in_order():
    for panel in (CATEGORY_PANEL, FORMAT_PANEL):
        assert list(panel_help(panel)) == list(panel[1])


# The Help's examples: (the instruction as the Help writes it, the item whose paragraph
# names it, the item it counts in). The two differ where the Help tells of an instruction
# that counts elsewhere; COUNTS_AS has the words of its sentence that say where.
CATEGORY_EXAMPLES = [
    ("ADD R0, R1, R2", "alu", "alu"), ("SUB R0, R0, #1", "alu", "alu"),
    ("MOV R0, #5", "alu", "alu"), ("CMP R0, #10", "alu", "alu"),
    ("AND R0, R0, #15", "alu", "alu"), ("LSL R0, R0, #2", "alu", "alu"),
    ("ADDNE R0, R0, #1", "alu", "alu"), ("MOV PC, LR", "alu", "alu"), ("NOP", "alu", "alu"),
    ("VADD.F32 S0, S1, S2", "alu", "alu"), ("STMDB R1!, {R2, R3}", "alu", "alu"),
    ("POPNE {R4, R5}", "alu", "alu"), ("LDMNE R1, {R2}", "alu", "alu"),
    ("STMDB SP!, {R4, R5}", "alu", "reg_transfer"), ("PUSHNE {R4}", "alu", "cond_load_other"),
    ("BNE loop", "branch", "branch"),
    ("LDRB R0, [R1]", "memory", "memory"), ("STRB R0, [R1, #1]", "memory", "memory"),
    ("LDRSB R0, [R1]", "memory", "memory"),
    ("LDR R0, [R1]", "reg_transfer", "reg_transfer"),
    ("STR R0, [R1, #4]", "reg_transfer", "reg_transfer"),
    ("LDR R0, =value", "reg_transfer", "reg_transfer"),
    ("PUSH {R4, LR}", "reg_transfer", "reg_transfer"),
    ("POP {R4, PC}", "reg_transfer", "reg_transfer"),
    ("LDR R0, =5", "reg_transfer", "alu"),
    ("LDRNE R0, [R1]", "cond_load_other", "cond_load_other"),
    ("STREQ R0, [R1, #4]", "cond_load_other", "cond_load_other"),
    ("LDRNEB R0, [R1]", "cond_load_other", "cond_load_other"),
    ("SVC #1", "cond_load_other", "cond_load_other"),
]
FORMAT_EXAMPLES = [
    ("ADD R0, R1, R2", "fmt_dp_reg", "fmt_dp_reg"), ("MOV R4, R0", "fmt_dp_reg", "fmt_dp_reg"),
    ("CMP R0, R1", "fmt_dp_reg", "fmt_dp_reg"), ("LSL R0, R0, R1", "fmt_dp_reg", "fmt_dp_reg"),
    ("ADD R0, R0, #1", "fmt_dp_imm", "fmt_dp_imm"), ("MOV R0, #5", "fmt_dp_imm", "fmt_dp_imm"),
    ("CMP R0, #10", "fmt_dp_imm", "fmt_dp_imm"), ("LSL R0, R0, #2", "fmt_dp_imm", "fmt_dp_imm"),
    ("ADD R4, R0, R0, LSL #1", "fmt_dp_imm", "fmt_dp_imm"), ("NOP", "fmt_dp_imm", "fmt_dp_reg"),
    ("VMUL.F32 S0, S0, S1", "fmt_dp_imm", "fmt_dp_reg"),
    ("VLDR D1, [R1, #8]", "fmt_dp_imm", "fmt_dp_imm"),
    ("LDR R0, [R1]", "fmt_ls_imm", "fmt_ls_imm"), ("STR R0, [R1, #4]", "fmt_ls_imm", "fmt_ls_imm"),
    ("LDR R0, =value", "fmt_ls_imm", "fmt_ls_imm"), ("LDR R0, =5", "fmt_ls_imm", "fmt_dp_imm"),
    ("LDR R0, [R1, R9]", "fmt_ls_imm", "fmt_ls_imm"),
    ("LDR R0, [R1], R2", "fmt_ls_imm", "fmt_ls_imm"),
    ("LDR R0, [R1, R2]", "fmt_ls_reg", "fmt_ls_reg"),
    ("STR R0, [R1, R2, LSL #2]", "fmt_ls_reg", "fmt_ls_reg"),
    ("LDR R0, [R1, -R2]", "fmt_ls_reg", "fmt_ls_reg"),
    ("PUSH {R4, LR}", "fmt_lsm", "fmt_lsm"), ("POP {R4, PC}", "fmt_lsm", "fmt_lsm"),
    ("POP {PC}", "fmt_lsm", "fmt_lsm"), ("LDR R4, [SP], #4", "fmt_lsm", "fmt_lsm"),
    ("PUSH {LR}", "fmt_lsm", "fmt_ls_imm"),        # the assembler's STR LR, [SP, #-4]!
    ("SVC #1", "fmt_svc", "fmt_svc"),
]
COUNTS_AS = {
    "alu": {"STMDB SP!, {R4, R5}": "of Memory (Reg-to-Reg)", "PUSHNE {R4}": "a conditional store"},
    "reg_transfer": {"LDR R0, =5": "an ALU instruction"},
    "fmt_dp_imm": {"NOP": "count as register", "VMUL.F32 S0, S0, S1": "count as register"},
    "fmt_ls_imm": {"LDR R0, =5": "counts as Data Processing (Immediate)"},
    "fmt_lsm": {"PUSH {LR}": "counts as Load/Store (Immediate)"},
}
# Instructions the Help names by their mnemonic: (the mnemonic, an instruction of it, the
# item whose paragraph names it, where it counts).
NAMED = [
    ("MUL", "MUL R0, R1, R2", "alu"), ("MLA", "MLA R0, R1, R2, R3", "alu"),
    ("UMULL", "UMULL R0, R1, R2, R3", "alu"), ("VLDR", "VLDR D1, [R1]", "alu"),
    ("VPUSH", "VPUSH {D8}", "alu"),
    ("B", "B loop", "branch"), ("BL", "BL loop", "branch"), ("BX", "BX LR", "branch"),
    ("BLX", "BLX R3", "branch"),
    ("LDRH", "LDRH R0, [R1]", "reg_transfer"), ("STRH", "STRH R0, [R1]", "reg_transfer"),
    ("LDRSH", "LDRSH R0, [R1]", "reg_transfer"), ("LDRD", "LDRD R2, R3, [R1]", "reg_transfer"),
    ("LDMIA", "LDMIA R1, {R2, R3}", "reg_transfer"),
    ("STMIA", "STMIA R1, {R2, R3}", "reg_transfer"),
    ("BKPT", "BKPT #0", "cond_load_other"),
    ("LDRB", "LDRB R0, [R1]", "fmt_ls_imm"), ("STRB", "STRB R0, [R1]", "fmt_ls_imm"),
    ("LDRH", "LDRH R0, [R1, #2]", "fmt_ls_imm"), ("STRH", "STRH R0, [R1]", "fmt_ls_imm"),
    ("B", "B loop", "fmt_branch"), ("BL", "BL loop", "fmt_branch"),
    ("BX", "BX LR", "fmt_branch"), ("BLX", "BLX R3", "fmt_branch"),
    ("MUL", "MUL R0, R1, R2", "fmt_mul"), ("MLA", "MLA R0, R1, R2, R3", "fmt_mul"),
    ("MLS", "MLS R0, R1, R2, R3", "fmt_mul"), ("SMULL", "SMULL R0, R1, R2, R3", "fmt_mul"),
    ("UMULL", "UMULL R0, R1, R2, R3", "fmt_mul"), ("SMLAL", "SMLAL R0, R1, R2, R3", "fmt_mul"),
    ("UMLAL", "UMLAL R0, R1, R2, R3", "fmt_mul"),
    ("BKPT", "BKPT #0", "fmt_svc"),
]


def word(build, line):
    """The word of an instruction, assembled with the labels the Help's examples name."""
    program = build(f".global _start\n_start:\nloop:   {line}\n        .data\nvalue:  .word 0\n")
    section = next(s for s in program.sections if s.executable)
    return struct.unpack_from("<I", section.data)[0]


def counted_in(build, line):
    """(format, class) of an instruction."""
    kind, group = classify(word(build, line))
    return FORMATS[kind], CLASSES[group]


def paragraph(item):
    """The Help's paragraph about a category (in CLASSES) or a format (in FORMATS)."""
    if item in CLASSES:
        return panel_help(CATEGORY_PANEL)[CATEGORY_PANEL[1][CLASSES.index(item)]]
    return panel_help(FORMAT_PANEL)[FORMAT_PANEL[1][FORMATS.index(item)]]


@pytest.mark.parametrize("line, item, kind", CATEGORY_EXAMPLES + FORMAT_EXAMPLES)
def test_the_help_s_examples_count_where_it_says(build, line, item, kind):
    """So that the Help and DynARMic's rules cannot drift apart."""
    text = paragraph(item)
    assert line in text
    if kind != item:
        assert any(COUNTS_AS[item][line] in part for part in text.split(". ") if line in part)
    assert kind in counted_in(build, line)


@pytest.mark.parametrize("mnemonic, line, item", NAMED)
def test_the_instructions_the_help_names_count_where_it_says(build, mnemonic, line, item):
    assert re.search(rf"(?<![\w.]){mnemonic}(?!\w)", paragraph(item)), mnemonic
    assert item in counted_in(build, line)


def test_a_push_of_sp_alone_is_load_store_multiple(build):
    """The Help's "a PUSH of one register other than SP": the assembler keeps PUSH {SP} as
    STMDB SP!, {SP}."""
    assert counted_in(build, "PUSH {SP}")[0] == "fmt_lsm"


def test_the_help_credits_dynarmic():
    text = " ".join(HELP.split())
    assert ("The Dynamic Instruction Counter and its classification come from DynARMic "
            "(GLSVLSI 2026), a dynamic ARM instruction counting tool") in text


# Words the counter never uses: it counts instructions, nothing else.
NO_CYCLES = ("cycle", "cpi", "clock rate", "run time")


def test_nothing_in_the_counter_is_about_cycles():
    """No cycles, CPI, clock rate or run time: not in the module's code, names, comments or
    texts, nor in its Help."""
    source = Path(counter.__file__).read_text(encoding="utf-8")
    for text in (source, HELP):
        text = " ".join(text.split()).lower()
        for words in NO_CYCLES:
            assert words not in text, words
