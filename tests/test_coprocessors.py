# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""What Help > ARES > Limits says of the coprocessors, against instructions that really run."""

import pytest

from ares import helptext
from ares.machine import Machine, StopReason

SET_UP = """\
        .global _start
_start: LDR     R0, =0xA5A5A5A5
        LDR     R1, =buffer
        LDR     R2, =0x12345678
"""
END = """
        B       .
        .data
buffer: .word   1, 2, 3, 4
"""
FIRST = 3                       # instructions before the one tested
OTHERS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13)


@pytest.fixture
def stepped(build):
    """stepped(lines): a Machine that has stepped through SET_UP and lines, or stopped there."""
    def _stepped(*lines):
        machine = Machine(build(SET_UP + "".join(f"        {line}\n" for line in lines) + END))
        for _ in range(FIRST + len(lines)):
            machine.step()
            if machine.stop_reason is not None:
                break
        return machine
    return _stepped


def undefined(machine):
    return (machine.stop_reason is StopReason.ERROR and "undefined instruction" in machine.error
            and machine.error_address == 4 * FIRST)


def test_the_limits_say_what_these_tests_show():
    words = " ".join(helptext.LIMITS.split())
    assert ("Only these coprocessor instructions work: those of the floating-point unit, "
            "coprocessors 10 and 11, and `MRC` and `MCR` on a register of 14, the debug unit, or 15, "
            "the system's, that can be read or written that way. Any other, such as `CDP` or `MRRC` "
            "on 14 or 15, is an undefined instruction: unless its condition fails, it ends the "
            "program with a runtime error.") in words


@pytest.mark.parametrize("line, value", [
    ("MRC P15, 0, R0, C0, C0, 0", 0x410FC090),      # the CPU's ID: a Cortex-A9
    ("MRC P14, 0, R0, C0, C0, 0", 0x35141000),      # the debug unit's ID
    ("MRC P10, 7, R0, C0, C0, 0", 0x41033090),      # the floating-point unit's ID, FPSID
    ("MRC P10, 0, R0, C0, C0, 0", 0),               # VMOV R0, S0
    ("MRC P11, 0, R0, C0, C0, 0", 0),               # VMOV.32 R0, D0[0]
])
def test_a_register_that_can_be_read_is_read(stepped, line, value):
    machine = stepped(line)
    assert machine.stop_reason is None and machine.reg(0) == value


@pytest.mark.parametrize("write, read", [
    ("MCR P15, 0, R2, C13, C0, 3", "MRC P15, 0, R0, C13, C0, 3"),   # a thread ID register
    ("MCR P14, 0, R2, C0, C0, 4", "MRC P14, 0, R0, C0, C0, 4"),     # a debug breakpoint's value
    ("MCR P10, 0, R2, C0, C0, 0", "MRC P10, 0, R0, C0, C0, 0"),     # VMOV S0, R2 and back
])
def test_a_register_that_can_be_written_keeps_the_value(stepped, write, read):
    machine = stepped(write, read)
    assert machine.stop_reason is None and machine.reg(0) == 0x12345678


@pytest.mark.parametrize("line", ["LDC P10, C0, [R1]", "STC P11, C0, [R1]",
                                  "CDP P10, 0, C0, C0, C0, 0", "MCRR P11, 1, R0, R2, C0"])
def test_the_other_kinds_of_instruction_work_on_the_floating_point_unit(stepped, line):
    assert stepped(line).stop_reason is None


@pytest.mark.parametrize("line", [
    "MRC P14, 0, R0, C0, C6, 0",        # no such register
    "MRC P14, 1, R0, C0, C0, 0",
    "MRC P15, 0, R0, C15, C15, 7",
    "MCR P15, 0, R2, C15, C15, 7",
    "MCR P14, 0, R2, C0, C0, 0",        # it can be read, not written
    "MRC P14, 0, R0, C1, C0, 4",        # it can be written, not read
])
def test_a_register_that_cannot_be_used_that_way_ends_the_program(stepped, line):
    assert undefined(stepped(line))


@pytest.mark.parametrize("cp", (14, 15))
@pytest.mark.parametrize("form", [
    "CDP P{}, 0, C0, C0, C0, 0", "LDC P{}, C0, [R1]", "LDC P{}, C5, [R1]", "STC P{}, C0, [R1]",
    "STC P{}, C5, [R1]", "LDCL P{}, C5, [R1]", "STCL P{}, C5, [R1]", "MCRR P{}, 0, R0, R2, C1",
    "MRRC P{}, 0, R0, R2, C1", "MCRR P{}, 0, R0, R2, C2", "MRRC P{}, 0, R0, R2, C2"])
def test_on_14_and_15_only_mrc_and_mcr_work(stepped, cp, form):
    assert undefined(stepped(form.format(cp)))


@pytest.mark.parametrize("cp", OTHERS)
@pytest.mark.parametrize("form", [
    "MRC P{}, 0, R0, C0, C0, 0", "MCR P{}, 0, R2, C0, C0, 0", "MRRC P{}, 0, R0, R2, C1",
    "MCRR P{}, 0, R0, R2, C1", "LDC P{}, C0, [R1]", "STC P{}, C0, [R1]",
    "CDP P{}, 0, C0, C0, C0, 0"])
def test_the_other_coprocessors_do_not_exist(stepped, cp, form):
    assert undefined(stepped(form.format(cp)))


@pytest.mark.parametrize("cp", (6, 10, 11, 14, 15))
@pytest.mark.parametrize("form", [
    "MRC2 P{}, 0, R0, C0, C0, 0", "MCR2 P{}, 0, R2, C0, C0, 0", "MRRC2 P{}, 0, R0, R2, C1",
    "MCRR2 P{}, 0, R0, R2, C1", "LDC2 P{}, C0, [R1]", "STC2 P{}, C0, [R1]",
    "CDP2 P{}, 0, C0, C0, C0, 0"])
def test_the_second_encodings_work_on_none_of_them(stepped, cp, form):
    assert undefined(stepped(form.format(cp)))


@pytest.mark.parametrize("line", ["MRCNE P3, 0, R0, C0, C0, 0", "CDPNE P3, 0, C0, C0, C0, 0",
                                  "LDCNE P14, C5, [R1]", "MRRCNE P15, 0, R0, R2, C1"])
def test_with_a_failed_condition_it_does_nothing(stepped, line):
    machine = stepped("CMP R0, R0", line)
    assert machine.stop_reason is None and machine.reg(0) == 0xA5A5A5A5
    assert machine.pc == 4 * (FIRST + 2)
