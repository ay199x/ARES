# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Floating Point Representation without its window: the fields' texts, what each field
takes, how the bits give the value, and the model that follows a register S0-S31."""

import time

import pytest
from test_benchmark import BENCHMARK, TOOL_SECONDS

from ares.floats import SINGLE_NAN
from ares.gui.tools.fpr import (DIGITS, FIELDS, NOTES, FloatModel, formula, parse, texts,
                                wrong)
from ares.machine import Machine, StopReason
from ares.runner import Runner

PROGRAM = """\
        .data
values: .float  1.5, -0.1
        .global _start
        .text
_start: LDR     R1, =values
        VLDR    S2, [R1]
        VLDR    S3, [R1, #4]
        VADD.F32 S4, S2, S3
        SVC     #10
"""
ONE_AND_A_HALF, MINUS_A_TENTH, SUM = 0x3FC00000, 0xBDCCCCCD, 0x3FB33333     # 1.5, -0.1, 1.4


def make(build, source=PROGRAM):
    machine = Machine(build(source))
    return machine, Runner(machine)


def written(parts):
    """The formula as a line of text: ^ before a raised part, the hidden bit in brackets."""
    return "".join(f"^{text}" if kind == "power" else f"[{text}]" if kind == "hidden" else text
                   for text, kind, _ in parts)


def targets(parts):
    """{role: the indices of the parts an arrow points at}."""
    found = {}
    for index, (_, _, roles) in enumerate(parts):
        for role in roles:
            found.setdefault(role, []).append(index)
    return found


# The fields' texts ----------------------------------------------------------------

@pytest.mark.parametrize("bits, expected", [
    (0, ("00000000", "0", "00000000", "0" * 23, "0.0")),
    (ONE_AND_A_HALF, ("3FC00000", "0", "01111111", "1" + "0" * 22, "1.5")),
    (MINUS_A_TENTH, ("BDCCCCCD", "1", "01111011", "10011001100110011001101", "-0.1")),
    (0x80000000, ("80000000", "1", "00000000", "0" * 23, "-0.0")),
    (0x00000001, ("00000001", "0", "00000000", "0" * 22 + "1", "1.4E-45")),
    (0x7F7FFFFF, ("7F7FFFFF", "0", "11111110", "1" * 23, "3.4028235E38")),
    (0x7F800000, ("7F800000", "0", "11111111", "0" * 23, "Infinity")),
    (0xFF800000, ("FF800000", "1", "11111111", "0" * 23, "-Infinity")),
    (0x7FC00001, ("7FC00001", "0", "11111111", "1" + "0" * 21 + "1", "NaN")),
])
def test_the_texts_of_the_fields(bits, expected):
    assert FIELDS == ("hex", "sign", "exponent", "fraction", "decimal")
    assert texts(bits) == dict(zip(FIELDS, expected))
    assert [len(texts(bits)[name]) for name in DIGITS] == [8, 1, 8, 23]


# What each field takes --------------------------------------------------------------

@pytest.mark.parametrize("text, bits", [
    ("3fc00000", ONE_AND_A_HALF), ("3FC00000", ONE_AND_A_HALF), ("0x40490fdb", 0x40490FDB),
    ("0X1", 1), (" 7f8 ", 0x7F8), ("FFFFFFFF", 0xFFFFFFFF),
    ("", None), ("123456789", None), ("0x", None), ("12G", None), ("-1", None),
    ("0x 1", None), ("1 2", None), ("１", None),
])
def test_the_hexadecimal_field_takes_up_to_8_digits(text, bits):
    """Fewer digits are filled up with zeros on the left; the old value plays no part."""
    assert parse("hex", text, 0xDEADBEEF) == bits


@pytest.mark.parametrize("field, text, old, bits", [
    ("sign", "1", ONE_AND_A_HALF, 0xBFC00000),
    ("sign", "0", 0xBFC00000, ONE_AND_A_HALF),
    ("sign", " 1 ", 0, 0x80000000),
    ("sign", "2", 0, None), ("sign", "10", 0, None), ("sign", "", 0, None),
    ("exponent", "10000000", ONE_AND_A_HALF, 0x40400000),         # 3.0
    ("exponent", "1", 0x80000000, 0x80800000),                    # 00000001: the sign stays
    ("exponent", "11111111", 0, 0x7F800000),
    ("exponent", "111111111", 0, None), ("exponent", "12", 0, None), ("exponent", "", 0, None),
    ("fraction", "1", 0x3F800000, 0x3F800001),
    ("fraction", "1" * 23, 0x3F800000, 0x3FFFFFFF),
    ("fraction", "1" * 24, 0, None), ("fraction", "01a", 0, None), ("fraction", "", 0, None),
])
def test_a_binary_field_replaces_its_own_bits(field, text, old, bits):
    assert parse(field, text, old) == bits


@pytest.mark.parametrize("text, bits", [
    ("1.5", ONE_AND_A_HALF), ("-0.1", MINUS_A_TENTH), ("1.4", SUM), (".5", 0x3F000000),
    ("2e-3", 0x3B03126F), ("1E39", 0x7F800000), ("-inf", 0xFF800000),
    ("Infinity", 0x7F800000), ("NaN", SINGLE_NAN), ("-0", 0x80000000),
    ("abc", None), ("0x3fc00000", None), ("1.5.5", None), ("", None),
])
def test_the_decimal_field_reads_numbers_as_the_register_tabs_do(text, bits):
    """Rounded to the nearest single; the old value plays no part."""
    assert parse("decimal", text, 0x12345678) == bits


def test_what_a_wrong_entry_says():
    assert wrong("hex", "XYZ") == "Hexadecimal: type 1 to 8 digits 0-9 or A-F (0x before them " \
                                  "is allowed)."
    assert wrong("sign", "2") == "Sign: type one bit, 0 for positive or 1 for negative."
    assert wrong("exponent", "2") == "Exponent: type 1 to 8 bits, each 0 or 1."
    assert wrong("fraction", "2") == "Fraction: type 1 to 23 bits, each 0 or 1."
    assert wrong("decimal", "abc") == ("Decimal: abc is not a number. Type, for example, 1.5, "
                                       "-0.25, 6.02E23, Infinity or NaN.")
    long = wrong("decimal", "1" * 40)
    assert "1" * 16 + "..." in long and "1" * 17 not in long


# How the bits give the value ------------------------------------------------------------

@pytest.mark.parametrize("bits, line, label, note", [
    (ONE_AND_A_HALF, "(-1)^0 × 2^0 × [1].10000000000000000000000 =", "127 - 127", "normal"),
    (MINUS_A_TENTH, "(-1)^1 × 2^-4 × [1].10011001100110011001101 =", "123 - 127", "normal"),
    (0x7F7FFFFF, "(-1)^0 × 2^127 × [1].11111111111111111111111 =", "254 - 127", "normal"),
    (0x00800000, "(-1)^0 × 2^-126 × [1].00000000000000000000000 =", "1 - 127", "normal"),
    (0x00000001, "(-1)^0 × 2^-126 × [0].00000000000000000000001 =", "0 + 1 - 127", "small"),
    (0, "(-1)^0 × 2^-126 × [0].00000000000000000000000 =", "0 + 1 - 127", "small"),
    (0x80000000, "(-1)^1 × 2^-126 × [0].00000000000000000000000 =", "0 + 1 - 127", "small"),
    (0x7F800000, "(-1)^0 × Infinity =", "255", "infinite"),
    (0xFF800000, "(-1)^1 × Infinity =", "255", "infinite"),
    (0x7FC00001, "NaN =", "255", "nan"),
])
def test_the_formula_under_the_bits(bits, line, label, note):
    """Normal numbers have a hidden 1, zero and the subnormal numbers a hidden 0 and the
    exponent 1 - 127; an exponent of all ones gives infinity or NaN."""
    parts, arrow_label, arrow_note = formula(bits)
    assert written(parts) == line
    assert arrow_label == label and arrow_note == NOTES[note]


def test_the_arrows_point_at_the_parts_made_from_each_field():
    assert targets(formula(ONE_AND_A_HALF)[0]) == {"sign": [1], "exponent": [3],
                                                   "fraction": [5, 6]}
    assert targets(formula(0x7F800000)[0]) == {"sign": [1], "exponent": [3], "fraction": [3]}
    assert targets(formula(SINGLE_NAN)[0]) == {"sign": [0], "exponent": [0], "fraction": [0]}


# The model ---------------------------------------------------------------------------

def test_not_connected_it_is_a_converter(build):
    machine, runner = make(build)
    model = FloatModel()
    assert (model.bits, model.register, model.connected) == (0, 0, False)
    model.observe(machine)                  # not connected: the program is not observed
    assert model.machine is None
    model.take(ONE_AND_A_HALF)
    runner.run()
    assert not model.update() and model.bits == ONE_AND_A_HALF
    assert machine.single(0) == 0           # nothing written
    model.take(-1)
    assert model.bits == 0xFFFFFFFF


def test_connected_it_follows_the_chosen_register(build):
    machine, runner = make(build)
    model = FloatModel()
    assert not model.choose(2)              # not connected: nothing to show yet
    model.connect(machine)
    assert model.machine is machine and model.bits == 0
    runner.step()
    assert not model.update()               # LDR: S2 is still 0
    runner.step()
    assert model.update() and model.bits == ONE_AND_A_HALF
    assert not model.update()               # nothing new the second time
    assert model.choose(3) and model.bits == 0 and model.register == 3
    runner.run()
    assert model.update() and model.bits == MINUS_A_TENTH
    assert model.choose(4) and model.bits == SUM


def test_it_installs_no_hook(build):
    machine = Machine(build(PROGRAM))
    hooks = len(machine.uc._callbacks)
    model = FloatModel()
    model.connect(machine)
    assert not machine.observers.active and len(machine.uc._callbacks) == hooks
    model.disconnect()
    assert len(machine.uc._callbacks) == hooks


def test_it_follows_across_reset_backstep_and_assemble(build):
    machine, runner = make(build)
    model = FloatModel()
    model.choose(2)
    model.connect(machine)
    for _ in range(3):
        runner.step()
    model.update()
    assert model.bits == ONE_AND_A_HALF
    model.choose(3)
    assert model.bits == MINUS_A_TENTH
    runner.backstep()                       # VLDR S3 undone
    assert model.update() and model.bits == 0
    runner.run()
    assert model.update() and model.bits == MINUS_A_TENTH
    runner.reset()                          # the registers start again at 0
    assert model.update() and model.bits == 0
    runner.run()
    model.update()
    other, other_runner = make(build)       # a new Assemble: the window passes the new machine
    model.observe(other)
    assert model.connected and model.machine is other and model.bits == 0
    other_runner.run()
    model.update()
    assert model.bits == MINUS_A_TENTH
    model.observe(None)                     # the program's file closed: still connected
    assert model.connected and model.machine is None and model.bits == MINUS_A_TENTH
    assert not model.update()


def test_disconnected_it_keeps_the_value_shown(build):
    machine, runner = make(build)
    model = FloatModel()
    model.choose(4)
    model.connect(machine)
    runner.run()
    model.disconnect()                      # what the program did until now is taken in
    assert not model.connected and model.machine is None and model.bits == SUM
    runner.reset()
    assert not model.update() and model.bits == SUM


def test_connected_without_a_program_it_waits_for_one(build):
    model = FloatModel()
    model.take(ONE_AND_A_HALF)
    model.connect(None)
    assert model.connected and model.machine is None and not model.update()
    assert model.bits == ONE_AND_A_HALF
    machine, runner = make(build)
    model.observe(machine)
    assert model.bits == 0                  # S0 of the program
    model.choose(2)
    runner.run()
    model.update()
    assert model.bits == ONE_AND_A_HALF


def test_reset_sets_the_value_to_zero(build):
    machine, runner = make(build)
    model = FloatModel()
    model.choose(2)
    model.connect(machine)
    runner.run()
    model.update()
    model.reset()
    assert model.bits == 0 and model.register == 2
    assert machine.single(2) == ONE_AND_A_HALF      # the window writes the register itself


# Speed --------------------------------------------------------------------------------

@pytest.mark.serial
def test_ten_million_instructions_with_the_tool_connected(build):
    """Connected, the tool adds nothing to a run: it reads its register only when asked."""
    machine = Machine(build(BENCHMARK.read_text()))
    model = FloatModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    assert not machine.observers.active
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s"
