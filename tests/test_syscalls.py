# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""System calls: output of each service, registers and flags preserved."""

import time

import pytest
from unicorn import arm_const as arm

from ares.console import FINISHED_ERROR
from ares.floats import double_bits, single_bits
from ares.machine import DDR_END, StopReason
from ares.runner import State
from ares.syscalls import (CONFIRM, INPUT_DOUBLE, INPUT_FLOAT, INPUT_STRING, MESSAGE,
                           MESSAGE_DOUBLE, MESSAGE_FLOAT, MESSAGE_INTEGER, MESSAGE_STRING,
                           SERVICES, JavaRandom, dialog_text)

FINISHED = "-- program is finished running --\n"


def program(body, data=""):
    return ("        .global _start\n        .text\n_start:\n" + body +
            "        B       .\n        .data\n" + data)


@pytest.mark.parametrize("value, text", [
    ("0", "0"), ("42", "42"), ("0xFFFFFFFF", "-1"),
    ("0x80000000", "-2147483648"), ("0x7FFFFFFF", "2147483647"),
])
def test_print_integer(run, value, text):
    machine = run(program(f"        LDR R0, ={value}\n        SVC #1\n"))
    assert machine.console.text == text + "\n" + FINISHED


@pytest.mark.parametrize("value, text", [
    ("0", "0x00000000"), ("0x17F", "0x0000017f"), ("0xDEADBEEF", "0xdeadbeef"),
])
def test_print_hexadecimal(run, value, text):
    machine = run(program(f"        LDR R0, ={value}\n        SVC #34\n"))
    assert machine.console.text == text + "\n" + FINISHED


def test_print_character_uses_low_byte(run):
    machine = run(program("        MOV R0, #'A'\n        SVC #11\n"
                          "        LDR R0, =0x142\n        SVC #11\n"
                          "        MOV R0, #10\n        SVC #11\n"))
    assert machine.console.text == "AB\n" + FINISHED


def test_print_string(run):
    machine = run(program("        LDR R0, =msg\n        SVC #4\n"
                          "        LDR R0, =empty\n        SVC #4\n",
                          'msg:    .asciz "Hi there, caf\\303\\251\\n"\nempty:  .asciz ""\n'))
    assert machine.console.text == "Hi there, café\n" + FINISHED


def test_print_string_across_ddr_pages(run):
    machine = run(program("""\
        LDR     R0, =0x000FFFFE
        MOV     R1, #'x'
        STRB    R1, [R0]
        MOV     R1, #'y'
        STRB    R1, [R0, #1]
        MOV     R1, #'z'
        STRB    R1, [R0, #2]
        SVC     #4
"""))
    assert machine.console.text == "xyz\n" + FINISHED


def test_print_string_bad_address_stops(run):
    machine = run(program("        LDR R0, =0x50000000\n        SVC #4\n"))
    assert machine.stop_reason is StopReason.ERROR
    assert machine.error == ("Runtime error at line 5 (address 0x00000004): "
                             "memory access out of range at 0x50000000")
    assert machine.pc == 4


def test_exit_stops_immediately(run):
    machine = run(program("        MOV R0, #1\n        SVC #10\n        MOV R0, #2\n"))
    assert machine.stop_reason is StopReason.EXIT
    assert machine.reg(0) == 1
    assert machine.console.text == FINISHED


def test_unknown_service_stops(run):
    machine = run(program("        NOP\n        SVC #99\n"))
    assert machine.stop_reason is StopReason.ERROR
    message = ("Runtime error at line 5 (address 0x00000004): "
               "unknown service number 99 (SVC #99)")
    assert machine.error == message
    assert machine.console.text == message + "\n" + FINISHED_ERROR + "\n"
    assert machine.pc == 4


# Registers and flags are preserved ---------------------------------------

PRESERVE = """\
        LDR     R0, =0x01234567
        LDR     R1, =0x89ABCDEF
        VMOV    D0, R0, R1
        VMOV    D1, R1, R0
        VMOV    Q1, Q0
        VMOV    Q2, Q0
        VMOV    Q3, Q0
        VMOV    Q4, Q0
        VMOV    Q5, Q0
        VMOV    Q6, Q0
        VMOV    Q7, Q0
        VMOV    Q8, Q0
        VMOV    Q9, Q0
        VMOV    Q10, Q0
        VMOV    Q11, Q0
        VMOV    Q12, Q0
        VMOV    Q13, Q0
        VMOV    Q14, Q0
        VMOV    Q15, Q0
        LDR     R0, =0x60000000     @ FPSCR: Z and C
        VMSR    FPSCR, R0
        LDR     R0, ={r0}
        LDR     R1, =0x11111111
        LDR     R2, =0x22222222
        LDR     R3, =0x33333333
        LDR     R4, =0x44444444
        LDR     R5, =0x55555555
        LDR     R6, =0x66666666
        LDR     R7, =0x77777777
        LDR     R8, =0x88888888
        LDR     R9, =0x99999999
        LDR     R10, =0xAAAAAAAA
        LDR     R11, =0xBBBBBBBB
        LDR     R12, =0xCCCCCCCC
        LDR     SP, =0xDDDDDDDD
        LDR     LR, =0xEEEEEEEE
        MSR     CPSR_f, #{flags}
        SVC     #{number}
"""
# number: (R0, R1, R2, R3 as written in LDR =..., or None for the default,
#          registers that hold results, typed input, dialog answer)
CASES = {
    1: ("-7", None, None, None, (), None, None),
    2: ("0", None, None, None, (), None, None),
    3: ("0", None, None, None, (), None, None),
    4: ("msg", None, None, None, (), None, None),
    5: ("0", None, None, None, (0,), "-12\n", None),
    6: ("0", None, None, None, (), "1.5\n", None),
    7: ("0", None, None, None, (), "-2.25\n", None),
    8: ("buffer", "8", None, None, (), "abc\n", None),
    9: ("10", None, None, None, (0,), None, None),
    10: ("0", None, None, None, (), None, None),
    11: ("65", None, None, None, (), None, None),
    12: ("0", None, None, None, (0,), "x\n", None),
    13: ("msg", "5", None, None, (0,), None, None),
    14: ("99", "buffer", "4", None, (0,), None, None),
    15: ("1", "msg", "4", None, (0,), None, None),
    16: ("99", None, None, None, (), None, None),
    17: ("3", None, None, None, (), None, None),
    30: ("0", None, None, None, (0, 1), None, None),
    31: ("60", "10", "0", "100", (), None, None),
    32: ("1", None, None, None, (), None, None),
    33: ("60", "10", "0", "100", (), None, None),
    34: ("0x1234", None, None, None, (), None, None),
    35: ("5", None, None, None, (), None, None),
    36: ("-1", None, None, None, (), None, None),
    40: ("1", "42", None, None, (), None, None),
    41: ("1", None, None, None, (0,), None, None),
    42: ("1", "10", None, None, (0,), None, None),
    43: ("1", None, None, None, (), None, None),
    44: ("1", None, None, None, (), None, None),
    50: ("msg", None, None, None, (0,), None, 1),
    51: ("msg", None, None, None, (0, 1), None, "5"),
    52: ("msg", None, None, None, (1,), None, "2.5"),
    53: ("msg", None, None, None, (1,), None, "2.5"),
    54: ("msg", "buffer", "8", None, (1,), None, "hey"),
    55: ("msg", "1", None, None, (), None, None),
    56: ("msg", "-4", None, None, (), None, None),
    57: ("msg", None, None, None, (), None, None),
    58: ("msg", None, None, None, (), None, None),
    59: ("msg", "msg", None, None, (), None, None),
}
# The floating-point register a service puts its result in.
VFP_RESULTS = {6: "S0", 43: "S0", 52: "S0", 7: "D0", 44: "D0", 53: "D0"}
DOUBLES = [getattr(arm, f"UC_ARM_REG_D{n}") for n in range(32)]


def test_every_service_has_a_preservation_case():
    assert sorted(CASES) == sorted(SERVICES)


@pytest.mark.parametrize("number", sorted(CASES))
@pytest.mark.parametrize("flags", [0xF0000000, 0x00000000, 0x60000000])
def test_service_preserves_registers_and_flags(make_runner, number, flags):
    r0, r1, r2, r3, results, typed, answer = CASES[number]
    source = program(PRESERVE.format(r0=r0, flags=hex(flags), number=number),
                     'msg:    .asciz "text"\nbuffer: .space 16\n')
    arguments = {1: r1, 2: r2, 3: r3}
    for n, value in arguments.items():
        if value is not None:
            source = source.replace(f"=0x{n}{n}{n}{n}{n}{n}{n}{n}", "=" + value)
    runner = make_runner(source, dialogs=lambda request: answer, input_text=typed)
    assert runner.run(time_limit=10) is State.FINISHED
    machine = runner.machine
    assert machine.stop_reason in (StopReason.EXIT, StopReason.SELF_BRANCH), machine.error
    labels = {"msg": machine.program.label_address("msg"),
              "buffer": machine.program.label_address("buffer")}

    def value(text, default):
        if text is None:
            return default
        return labels[text] if text in labels else int(text, 0) & 0xFFFFFFFF

    expected = [value(r0, 0)] + [value(arguments.get(n), 0x11111111 * n) for n in range(1, 4)]
    expected += [0x11111111 * n for n in range(4, 13)]
    for n in results:
        expected[n] = machine.reg(n)
    assert [machine.reg(n) for n in range(13)] == expected
    assert machine.reg(13) == 0xDDDDDDDD
    assert machine.reg(14) == 0xEEEEEEEE
    assert machine.cpsr == flags | 0x1D3
    # D0 to D31 (S0 to S31 are the halves of D0 to D15) and FPSCR
    expected = [0x89ABCDEF01234567, 0x0123456789ABCDEF] * 16
    if VFP_RESULTS.get(number) == "S0":
        expected[0] = expected[0] & ~0xFFFFFFFF | machine.single(0)
    elif VFP_RESULTS.get(number) == "D0":
        expected[0] = machine.double(0)
    assert list(machine.uc.reg_read_batch(DOUBLES)) == expected
    assert machine.vfp()[1] == 0x60000000


def test_service_table():
    assert sorted(SERVICES) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 30,
                                31, 32, 33, 34, 35, 36, 40, 41, 42, 43, 44, 50, 51, 52, 53, 54,
                                55, 56, 57, 58, 59]
    assert SERVICES[4].name == "print string"
    assert all(s.name and s.handler for s in SERVICES.values())


# Output formats -------------------------------------------------------------

@pytest.mark.parametrize("number, value, text", [
    (35, "5", "00000000000000000000000000000101"),
    (35, "0x80000001", "10000000000000000000000000000001"),
    (36, "0xFFFFFFFF", "4294967295"),
    (36, "42", "42"),
])
def test_print_binary_and_unsigned(run, number, value, text):
    machine = run(program(f"        LDR R0, ={value}\n        SVC #{number}\n"))
    assert machine.console.text == text + "\n" + FINISHED


# Reading typed input --------------------------------------------------------

READ_INTEGER = program("        SVC #5\n        SVC #1\n        MOV R0, #'|'\n        SVC #11\n"
                       "        SVC #5\n        SVC #1\n")


@pytest.mark.parametrize("typed, text", [
    ("42\n-7\n", "42|-7"),
    ("  +5 \r\n2147483647\n", "5|2147483647"),
    ("-2147483648\n0", "-2147483648|0"),
])
def test_read_integer(make_runner, typed, text):
    runner = make_runner(READ_INTEGER, input_text=typed)
    assert runner.run() is State.FINISHED
    assert runner.machine.console.text == text + "\n" + FINISHED


@pytest.mark.parametrize("typed", ["abc\n", "12a\n", "\n", "2147483648\n", "0x10\n", ""])
def test_read_integer_rejects_bad_input(make_runner, typed):
    runner = make_runner(READ_INTEGER, input_text=typed)
    runner.run()
    assert runner.machine.error == ("Runtime error at line 4 (address 0x00000000): "
                                    "invalid integer input (SVC #5)")


READ_STRING = program("""\
        LDR     R4, =buffer
        LDR     R5, =0xAAAAAAAA     @ fill pattern
        STR     R5, [R4]
        STR     R5, [R4, #4]
        STR     R5, [R4, #8]
        MOV     R0, R4
        LDR     R1, ={size}
        SVC     #8
        MOV     R0, R4
        MOV     R1, #12
        SVC     #8
""", "buffer: .space 12\nafter:  .space 12\n")


@pytest.mark.parametrize("size, first", [
    (12, b"hello\n\0"),         # fits: newline kept, then a zero byte
    (6, b"hello\0"),            # exactly n-1 characters: no newline
    (3, b"he\0"),               # cut to n-1 characters; the rest of the line is gone
    (1, b"\0"),                 # only the zero byte
    (0, b""),                   # nothing is written
    (-1, b""),
])
def test_read_string_follows_fgets(make_runner, size, first):
    runner = make_runner(READ_STRING.format(size=size), input_text="hello\nworld\n")
    assert runner.run() is State.FINISHED
    machine = runner.machine
    first_buffer = first + b"\xaa" * (12 - len(first))
    buffer = machine.program.label_address("buffer")
    assert machine.read_memory(buffer, 12) == b"world\n\0" + first_buffer[7:]


def test_read_string_first_line(make_runner):
    runner = make_runner(READ_STRING.format(size=6), input_text="hello there\r\nnext\n")
    while runner.machine.pc != 0x20:            # stop after the first SVC #8
        runner.step()
    buffer = runner.machine.program.label_address("buffer")
    assert runner.machine.read_memory(buffer, 8) == b"hello\0\xaa\xaa"
    runner.run()
    assert runner.machine.read_memory(buffer, 8) == b"next\n\0\xaa\xaa"


def test_read_string_at_end_of_input(make_runner):
    runner = make_runner(READ_STRING.format(size=12), input_text="")
    assert runner.run() is State.FINISHED
    buffer = runner.machine.program.label_address("buffer")
    assert runner.machine.read_memory(buffer, 4) == b"\n\0\xaa\xaa"


def test_read_character(make_runner):
    runner = make_runner(program("        SVC #12\n        MOV R4, R0\n        SVC #12\n"
                                 "        MOV R5, R0\n        SVC #12\n"),
                         input_text="abc\n\nz")
    assert runner.run() is State.FINISHED
    machine = runner.machine
    assert (machine.reg(4), machine.reg(5), machine.reg(0)) == (ord("a"), 10, ord("z"))


def test_read_character_at_end_of_input(make_runner):
    runner = make_runner(program("        SVC #12\n"), input_text="")
    runner.run()
    assert runner.machine.error.endswith("invalid character input (SVC #12)")


# Heap, exit, time -----------------------------------------------------------

def test_allocate_heap_memory(run):
    machine = run(program("""\
        MOV     R0, #5
        SVC     #9
        MOV     R4, R0
        MOV     R0, #8
        SVC     #9
        MOV     R5, R0
        MOV     R0, #0
        SVC     #9
        MOV     R6, R0
        MOV     R1, #77
        STR     R1, [R4]
""", "data:   .byte 1, 2, 3\n"))
    heap = (machine.program.sections[-1].end + 3) & ~3
    assert (machine.reg(4), machine.reg(5), machine.reg(6)) == (heap, heap + 8, heap + 16)
    assert machine.read_memory(heap, 4) == bytes([77, 0, 0, 0])


@pytest.mark.parametrize("size, message", [
    ("-1", "negative heap size -1 (SVC #9)"),
    ("0x40000000", "not enough memory for 1073741824 bytes of heap (SVC #9)"),
])
def test_allocate_heap_memory_errors(run, size, message):
    machine = run(program(f"        LDR R0, ={size}\n        SVC #9\n"))
    assert machine.error.endswith(message)


# The heap may grow up to the top of DDR3, or up to SP when SP is in DDR3
# above the heap's start. With SP at its start value 0 the stack is in the
# on-chip memory.
FILL_HEAP = """\
        MOV     R0, #0
        SVC     #9              @ where the heap starts
        MOV     R4, R0
        LDR     R1, ={limit}
        SUB     R0, R1, R0
        SVC     #9              @ all the memory up to the limit
        MOV     R5, R0
        MOV     R0, #0
        SVC     #9
        MOV     R6, R0          @ the end of the heap: the limit
        MOV     R0, #4
        SVC     #9              @ one word more is too much
"""


# A stack block that ends the program: SP set to its top is the heap's start.
STACK_BLOCK = "stack:  .space  64\nstack_top:\n"


@pytest.mark.parametrize("set_sp, data, limit", [
    ("", "", DDR_END),                                  # SP 0, its start value
    ("        LDR SP, =0x00100000\n", "", 0x00100000),  # SP in DDR3 above the heap
    ("        LDR SP, =0xFFFF8000\n", "", DDR_END),     # SP in the on-chip memory
    ("        MOV SP, #4\n", "", DDR_END),              # SP in DDR3 below the heap
    ("        LDR SP, =stack_top\n", STACK_BLOCK, DDR_END),     # SP at the heap's start
])
def test_the_heap_ends_at_the_top_of_ddr3_or_below_the_stack(run, set_sp, data, limit):
    machine = run(program(set_sp + FILL_HEAP.format(limit=hex(limit)), data))
    start = (max(s.end for s in machine.program.sections) + 3) & ~3
    assert machine.heap_start == start
    assert (machine.reg(4), machine.reg(5), machine.reg(6)) == (start, start, limit)
    assert machine.error.endswith("not enough memory for 4 bytes of heap (SVC #9)")
    assert machine.heap == limit


def test_a_stack_block_at_the_end_of_the_program_leaves_ddr3_to_the_heap(run):
    # SP starts at the heap's start and the stack grows down, away from the heap.
    machine = run(program("""\
        LDR     SP, =stack_top
        MOV     R0, #16
        SVC     #9
        MOV     R4, R0
        MOV     R0, #1
        PUSH    {R0}
        SVC     #10
""", STACK_BLOCK))
    start = machine.heap_start
    assert machine.stop_reason is StopReason.EXIT and machine.error is None
    assert machine.reg(4) == start and machine.heap == start + 16
    assert machine.reg(13) == start - 4
    assert machine.read_memory(start - 4, 4) == bytes([1, 0, 0, 0])


def test_the_heap_never_passes_sp_set_inside_it(run):
    machine = run(program("""\
        MOV     R0, #256
        SVC     #9
        MOV     R5, R0
        ADD     SP, R0, #128    @ SP inside the heap, above its start
        MOV     R0, #16
        SVC     #9              @ the heap's end is already above SP
"""))
    start = machine.heap_start
    assert machine.reg(5) == start and machine.reg(13) == start + 128
    assert machine.error == ("Runtime error at line 9 (address 0x00000014): "
                             "not enough memory for 16 bytes of heap (SVC #9)")
    assert machine.heap == start + 256


def test_exit_with_value(run):
    machine = run(program("        MOV R0, #3\n        SVC #17\n        MOV R0, #4\n"))
    assert machine.stop_reason is StopReason.EXIT and machine.exit_value == 3
    assert machine.reg(0) == 3
    assert machine.console.text == FINISHED


def test_system_time(run):
    before = time.time_ns() // 1_000_000
    machine = run(program("        SVC #30\n"))
    after = time.time_ns() // 1_000_000
    assert before <= (machine.reg(1) << 32 | machine.reg(0)) <= after


@pytest.mark.serial
@pytest.mark.parametrize("number, body, seconds", [
    (32, "        MOV R0, #120\n", 0.12),
    (33, "        MOV R0, #60\n        MOV R1, #120\n        MOV R2, #0\n"
         "        MOV R3, #100\n", 0.12),
])
def test_sleep_and_midi_wait(make_runner, number, body, seconds):
    runner = make_runner(program(body + f"        SVC #{number}\n"))
    start = time.perf_counter()
    assert runner.run() is State.FINISHED
    assert time.perf_counter() - start >= seconds


@pytest.mark.serial
def test_midi_out_does_not_wait(make_runner):
    runner = make_runner(program("        MOV R0, #60\n        LDR R1, =5000\n        SVC #31\n"))
    start = time.perf_counter()
    assert runner.run() is State.FINISHED
    assert time.perf_counter() - start < 1


# Files ------------------------------------------------------------------------

FILES = """\
        LDR     R0, =name
        MOV     R1, #{flags}
        MOV     R2, #0
        SVC     #13
        MOV     R4, R0              @ descriptor
        LDR     R1, =text
        MOV     R2, #6
        SVC     #15
        MOV     R5, R0              @ bytes written
        MOV     R0, R4
        SVC     #16
        LDR     R0, =name
        MOV     R1, #0
        SVC     #13
        MOV     R6, R0
        LDR     R1, =buffer
        MOV     R2, #64
        SVC     #14
        MOV     R7, R0              @ bytes read
        MOV     R0, R6
        LDR     R1, =buffer
        MOV     R2, #64
        SVC     #14
        MOV     R8, R0              @ 0 at the end of the file
        MOV     R0, R6
        SVC     #16
"""
FILES_DATA = 'name:   .asciz "notes.txt"\ntext:   .ascii "line 1"\nbuffer: .space 64\n'


def test_write_then_read_a_file(make_runner, tmp_path):
    runner = make_runner(program(FILES.format(flags=1), FILES_DATA))
    assert runner.run() is State.FINISHED
    machine = runner.machine
    assert machine.reg(4) == 3 and machine.reg(6) == 4
    assert (machine.reg(5), machine.reg(7), machine.reg(8)) == (6, 6, 0)
    assert (tmp_path / "notes.txt").read_bytes() == b"line 1"
    buffer = machine.program.label_address("buffer")
    assert machine.read_memory(buffer, 7) == b"line 1\0"


def test_append_to_a_file(make_runner, tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"old ")
    runner = make_runner(program(FILES.format(flags=9), FILES_DATA))
    assert runner.run() is State.FINISHED
    assert (tmp_path / "notes.txt").read_bytes() == b"old line 1"
    assert runner.machine.reg(7) == 10


@pytest.mark.parametrize("body", [
    "        LDR R0, =missing\n        MOV R1, #0\n        SVC #13\n",     # no such file
    "        LDR R0, =missing\n        MOV R1, #2\n        SVC #13\n",     # bad flags
    "        LDR R0, =empty\n        MOV R1, #1\n        SVC #13\n",       # no name
    "        MOV R0, #7\n        LDR R1, =missing\n        MOV R2, #4\n        SVC #14\n",
    "        MOV R0, #7\n        LDR R1, =missing\n        MOV R2, #4\n        SVC #15\n",
    "        MOV R0, #0\n        LDR R1, =missing\n        MOV R2, #4\n        SVC #15\n",
    "        MOV R0, #1\n        LDR R1, =missing\n        MOV R2, #4\n        SVC #14\n",
    "        MOV R0, #1\n        LDR R1, =missing\n        MVN R2, #0\n        SVC #15\n",
])
def test_file_errors_return_negative(run, body):
    machine = run(program(body, 'missing: .asciz "no/such/file.txt"\nempty: .byte 0\n'))
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert machine.reg(0) == 0xFFFFFFFF


def test_standard_descriptors(make_runner):
    runner = make_runner(program("""\
        MOV     R0, #1
        LDR     R1, =text
        MOV     R2, #3
        SVC     #15
        MOV     R0, #2
        LDR     R1, =text
        MOV     R2, #2
        SVC     #15
        MOV     R0, #0
        LDR     R1, =buffer
        MOV     R2, #3
        SVC     #14
        MOV     R4, R0
        MOV     R0, #0
        LDR     R1, =buffer + 3
        MOV     R2, #16
        SVC     #14
        MOV     R5, R0
        MOV     R0, #0
        LDR     R1, =buffer
        MOV     R2, #16
        SVC     #14
        MOV     R6, R0
        MOV     R0, #16
        SVC     #16             @ closing an unknown descriptor does nothing
""", 'text:   .ascii "abc"\nbuffer: .space 32\n'), input_text="hello\n")
    assert runner.run() is State.FINISHED
    machine = runner.machine
    assert machine.console.text == "abcab\n" + FINISHED
    assert (machine.reg(4), machine.reg(5), machine.reg(6)) == (3, 3, 0)
    assert machine.read_memory(machine.program.label_address("buffer"), 6) == b"hello\n"


def test_open_files_are_closed_when_the_program_ends(make_runner, tmp_path):
    runner = make_runner(program("""\
        LDR     R0, =name
        MOV     R1, #1
        SVC     #13
        LDR     R1, =name
        MOV     R2, #4
        SVC     #15
        SVC     #10
""", 'name:   .asciz "out.txt"\n'))
    runner.run()
    assert (tmp_path / "out.txt").read_bytes() == b"out."
    assert runner.machine.services.files == {}


# Random numbers -------------------------------------------------------------

def test_java_random_matches_known_values():
    assert JavaRandom(42).next_int() == -1170105035 & 0xFFFFFFFF
    assert JavaRandom(0).next_int() == -1155484576 & 0xFFFFFFFF
    assert JavaRandom(42).next_below(10) == 0
    generator = JavaRandom(7)
    values = [generator.next_below(6) for _ in range(1000)]
    assert set(values) == set(range(6))
    assert all(0 <= JavaRandom(s).next_below(1 << 20) < 1 << 20 for s in range(50))


RANDOM = """\
        MOV     R0, #{generator}
        LDR     R1, =42
        SVC     #40
        MOV     R0, #{generator}
        SVC     #41
        MOV     R4, R0
        MOV     R0, #{generator}
        MOV     R1, #100
        SVC     #42
        MOV     R5, R0
"""


def test_seeded_random_numbers_are_reproducible(run):
    first = run(program(RANDOM.format(generator=1)))
    second = run(program(RANDOM.format(generator=5)))
    reference = JavaRandom(42)
    expected = (reference.next_int(), reference.next_below(100))
    assert (first.reg(4), first.reg(5)) == expected
    assert (second.reg(4), second.reg(5)) == expected


def test_generators_are_independent(run):
    machine = run(program("""\
        MOV     R0, #1
        MOV     R1, #9
        SVC     #40
        MOV     R0, #2
        MOV     R1, #9
        SVC     #40
        MOV     R0, #1
        SVC     #41
        MOV     R4, R0
        MOV     R0, #2
        SVC     #41
        MOV     R5, R0
        MOV     R0, #3
        MOV     R1, #10
        SVC     #42             @ a generator nobody seeded
        MOV     R6, R0
"""))
    assert machine.reg(4) == machine.reg(5) == JavaRandom(9).next_int()
    assert machine.reg(6) < 10


def test_random_bound_must_be_positive(run):
    machine = run(program("        MOV R0, #1\n        MOV R1, #0\n        SVC #42\n"))
    assert machine.error.endswith("the bound must be positive, not 0 (SVC #42)")


# Dialogs ----------------------------------------------------------------------

DIALOG = program("""\
        LDR     R0, =msg
        LDR     R1, =buffer
        MOV     R2, #{size}
        SVC     #{number}
""", 'msg:    .asciz "Say something"\nbuffer: .space 8\n')


def dialog_run(make_runner, number, answer, size=8):
    asked = []
    runner = make_runner(DIALOG.format(number=number, size=size),
                         dialogs=lambda request: asked.append(request) or answer)
    assert runner.run() is State.FINISHED
    return runner.machine, asked


@pytest.mark.parametrize("answer, result", [(0, 0), (1, 1), (2, 2), (None, 2)])
def test_confirm_dialog(make_runner, answer, result):
    machine, asked = dialog_run(make_runner, 50, answer)
    assert machine.reg(0) == result
    assert (asked[0].dialog, asked[0].message) == (CONFIRM, "Say something")


@pytest.mark.parametrize("answer, value, status", [
    ("123", 123, 0), (" -9 ", -9, 0), ("12x", 0, -1), (None, 0, -2), ("", 0, -3),
])
def test_input_integer_dialog(make_runner, answer, value, status):
    machine, _ = dialog_run(make_runner, 51, answer)
    assert machine.reg(0) == value & 0xFFFFFFFF
    assert machine.reg(1) == status & 0xFFFFFFFF


@pytest.mark.parametrize("answer, size, data, status", [
    ("hi", 8, b"hi\n\0\xaa", 0),
    ("abcdefg", 8, b"abcdefg\0", 0),            # exactly n-1 characters: no newline
    ("abcdefghij", 8, b"abcdefg\0", -4),        # cut to fit
    ("a\ud83d", 8, b"a?\n\0\xaa", 0),            # half of a character beyond U+FFFF
    (None, 8, b"\xaa" * 5, -2),
    ("", 8, b"\xaa" * 5, -3),
])
def test_input_string_dialog(make_runner, answer, size, data, status):
    source = DIALOG.format(number=54, size=size).replace(
        "        SVC     #54\n",
        "        LDR     R5, =0xAAAAAAAA\n        STR R5, [R1]\n        STR R5, [R1, #4]\n"
        "        SVC     #54\n")
    runner = make_runner(source, dialogs=lambda request: answer)
    assert runner.run() is State.FINISHED
    machine = runner.machine
    buffer = machine.program.label_address("buffer")
    assert machine.read_memory(buffer, len(data)) == data
    assert machine.reg(1) == status & 0xFFFFFFFF
    assert runner.machine.request is None


def test_message_dialogs(make_runner):
    asked = []
    runner = make_runner(program("""\
        LDR     R0, =msg
        MOV     R1, #2
        SVC     #55
        LDR     R0, =msg
        MVN     R1, #4
        SVC     #56
        LDR     R0, =msg
        LDR     R1, =name
        SVC     #59
""", 'msg:    .asciz "Value: "\nname:   .asciz "ARM"\n'),
        dialogs=lambda request: asked.append(request))
    assert runner.run() is State.FINISHED
    assert [(r.service, r.dialog, r.value) for r in asked] == [
        (55, MESSAGE, 2), (56, MESSAGE_INTEGER, -5), (59, MESSAGE_STRING, "ARM")]
    assert [dialog_text(r) for r in asked] == ["Value: ", "Value: -5", "Value: ARM"]
    assert asked[0].dialog != INPUT_STRING


@pytest.mark.serial
def test_writing_past_the_end_of_memory_fails_at_once(make_runner):
    runner = make_runner(program("        MOV R0, #1\n        LDR R1, =text\n"
                                 "        LDR R2, =0x7FFFFFFF\n        SVC #15\n",
                                 'text:   .ascii "hi"\n'))
    start = time.perf_counter()
    assert runner.run() is State.FINISHED
    assert time.perf_counter() - start < 1
    assert runner.machine.error.endswith("memory access out of range at 0x40000000")
    assert runner.machine.console.text.startswith("Runtime error")      # nothing written


@pytest.mark.parametrize("typed, text", [
    ("0" * 5000 + "5\n" + "-" + "0" * 5000 + "7\n", "5|-7"),
])
def test_read_integer_with_many_leading_zeros(make_runner, typed, text):
    runner = make_runner(READ_INTEGER, input_text=typed)
    assert runner.run() is State.FINISHED
    assert runner.machine.console.text == text + "\n" + FINISHED


@pytest.mark.serial
def test_a_long_text_that_is_no_integer_is_refused_at_once():
    from ares.syscalls import parse_integer
    start = time.perf_counter()
    assert parse_integer("0" * 200_000 + "x") is None and parse_integer("+" + "0" * 200_000) == 0
    assert parse_integer("-" + "0" * 50 + "12") == -12 and parse_integer("000") == 0
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize("typed", ["1" + "0" * 5000 + "\n", "99999999999\n"])
def test_read_integer_rejects_too_many_digits(make_runner, typed):
    runner = make_runner(READ_INTEGER, input_text=typed)
    runner.run()
    assert runner.machine.error.endswith("invalid integer input (SVC #5)")
    machine, _ = dialog_run(make_runner, 51, typed.strip())
    assert machine.reg(1) == 0xFFFFFFFF         # -1: not a number


# Floating point ---------------------------------------------------------------

@pytest.mark.parametrize("bits, text", [
    (0x3FC00000, "1.5"), (0xC0200000, "-2.5"), (0x3DCCCCCD, "0.1"), (0x42C80000, "100.0"),
    (0x4B189680, "1.0E7"), (0x38D1B717, "1.0E-4"), (0x00000001, "1.4E-45"),
    (0x7F7FFFFF, "3.4028235E38"), (0x7F800000, "Infinity"), (0xFF800000, "-Infinity"),
    (0x7FC00000, "NaN"), (0x80000000, "-0.0"),
])
def test_print_float(run, bits, text):
    machine = run(program(f"        LDR R0, =0x{bits:08X}\n        VMOV S0, R0\n"
                          "        LDR R0, =0x40490FDB\n        VMOV S1, R0\n        SVC #2\n"))
    assert machine.console.text == text + "\n" + FINISHED      # S0 only, not S1


@pytest.mark.parametrize("bits, text", [
    (0x3FF8000000000000, "1.5"), (0x3FD3333333333334, "0.30000000000000004"),
    (0x3FB999999999999A, "0.1"), (0x4132D68700000000, "1234567.0"),
    (0x0000000000000001, "4.9E-324"), (0x7FEFFFFFFFFFFFFF, "1.7976931348623157E308"),
    (0xFFF0000000000000, "-Infinity"), (0x7FF8000000000000, "NaN"),
])
def test_print_double(run, bits, text):
    machine = run(program(f"        LDR R0, =0x{bits & 0xFFFFFFFF:08X}\n"
                          f"        LDR R1, =0x{bits >> 32:08X}\n        VMOV D0, R0, R1\n"
                          "        SVC #3\n"))
    assert machine.console.text == text + "\n" + FINISHED


READ_FLOAT = program("        SVC #6\n        SVC #2\n        MOV R0, #'|'\n        SVC #11\n"
                     "        SVC #7\n        SVC #3\n")


@pytest.mark.parametrize("typed, text", [
    ("2.5\n-0.1\n", "2.5|-0.1"),
    ("  1e3 \r\n.5\n", "1000.0|0.5"),
    ("0.1\n0.1\n", "0.1|0.1"),
    ("3\n-0\n", "3.0|-0.0"),
    ("inf\nNaN\n", "Infinity|NaN"),
    ("1e39\n1e309\n", "Infinity|Infinity"),         # too large: infinity
    ("1e-46\n-1e-400\n", "0.0|-0.0"),               # too small: zero
    ("16777217\n9007199254740993\n", "1.6777216E7|9.007199254740992E15"),   # rounded
])
def test_read_float_and_double(make_runner, typed, text):
    runner = make_runner(READ_FLOAT, input_text=typed)
    assert runner.run() is State.FINISHED
    assert runner.machine.console.text == text + "\n" + FINISHED


def test_read_float_sets_s0_and_read_double_d0(make_runner):
    runner = make_runner(program("        LDR R0, =0x12345678\n        VMOV D0, R0, R0\n"
                                 "        SVC #6\n        VMOV R4, R5, D0\n        SVC #7\n"),
                         input_text="1.5\n-2\n")
    assert runner.run() is State.FINISHED
    machine = runner.machine
    assert (machine.reg(4), machine.reg(5)) == (0x3FC00000, 0x12345678)   # S1 kept
    assert machine.double(0) == 0xC000000000000000


@pytest.mark.parametrize("typed", ["abc\n", "1.5.5\n", "\n", "0x10\n", "1,5\n", "1.5f\n", ""])
def test_read_float_rejects_bad_input(make_runner, typed):
    runner = make_runner(READ_FLOAT, input_text=typed)
    runner.run()
    assert runner.machine.error == ("Runtime error at line 4 (address 0x00000000): "
                                    "invalid float input (SVC #6)")


@pytest.mark.parametrize("typed", ["1\nx\n", "1\n"])
def test_read_double_rejects_bad_input(make_runner, typed):
    runner = make_runner(READ_FLOAT, input_text=typed)
    runner.run()
    assert runner.machine.error.endswith("invalid double input (SVC #7)")


def test_java_random_floats_match_known_values():
    # Java 21: new Random(42), then nextFloat() three times, nextDouble() three times, nextInt()
    generator = JavaRandom(42)
    assert [single_bits(generator.next_float()) for _ in range(3)] == [
        0x3F3A419D, 0x3D5FE8A0, 0x3F2EE7BB]
    assert [double_bits(generator.next_double()) for _ in range(3)] == [
        0x3FA88B8027841E70, 0x3FEE25776A3774EC, 0x3FE6A590AD530B55]
    assert generator.next_int() == 392236186
    assert all(0 <= JavaRandom(s).next_float() < 1 and 0 <= JavaRandom(s).next_double() < 1
               for s in range(200))


def test_random_float_and_double(run):
    machine = run(program("""\
        MOV     R0, #3
        LDR     R1, =42
        SVC     #40
        MOV     R0, #3
        SVC     #43
        VMOV    R4, S0
        MOV     R0, #3
        SVC     #44
        VMOV    R6, R7, D0
        MOV     R0, #9
        SVC     #43             @ a generator nobody seeded
        VMOV    R5, S0
"""))
    reference = JavaRandom(42)
    assert machine.reg(4) == single_bits(reference.next_float())
    assert machine.reg(7) << 32 | machine.reg(6) == double_bits(reference.next_double())
    assert 0 <= machine.reg(5) < 0x3F800000          # from 0 up to (not including) 1.0


FLOAT_DIALOG = program("""\
        LDR     R0, =0x12345678
        VMOV    D0, R0, R0      @ not zero before the dialog
        LDR     R0, =msg
        SVC     #{number}
""", 'msg:    .asciz "Radius?"\n')


@pytest.mark.parametrize("number, answer, value, status", [
    (52, "2.5", 0x40200000, 0), (52, " -1e-3 ", 0xBA83126F, 0), (52, "1e39", 0x7F800000, 0),
    (52, "x", 0, -1), (52, "0x10", 0, -1), (52, None, 0, -2), (52, "", 0, -3), (52, "  ", 0, -3),
    (53, "0.1", 0x3FB999999999999A, 0), (53, "-0", 1 << 63, 0), (53, "1.5e", 0, -1),
    (53, None, 0, -2), (53, "", 0, -3),
])
def test_input_float_and_double_dialogs(make_runner, number, answer, value, status):
    asked = []
    runner = make_runner(FLOAT_DIALOG.format(number=number),
                         dialogs=lambda request: asked.append(request) or answer)
    assert runner.run() is State.FINISHED
    machine = runner.machine
    if number == 52:                                    # S0, the low half of D0
        assert machine.double(0) == 0x12345678 << 32 | value
    else:
        assert machine.double(0) == value
    assert machine.reg(1) == status & 0xFFFFFFFF
    assert (asked[0].dialog, asked[0].message) == (
        INPUT_FLOAT if number == 52 else INPUT_DOUBLE, "Radius?")


def test_float_message_dialogs(make_runner):
    asked = []
    runner = make_runner(program("""\
        LDR     R0, =0x3FC00000
        VMOV    S0, R0
        LDR     R0, =msg
        SVC     #57
        LDR     R0, =0x9999999A
        LDR     R1, =0x3FB99999
        VMOV    D0, R0, R1
        LDR     R0, =msg
        SVC     #58
""", 'msg:    .asciz "Value: "\n'), dialogs=lambda request: asked.append(request))
    assert runner.run() is State.FINISHED
    assert [(r.service, r.dialog, r.value) for r in asked] == [
        (57, MESSAGE_FLOAT, "1.5"), (58, MESSAGE_DOUBLE, "0.1")]
    assert [dialog_text(r) for r in asked] == ["Value: 1.5", "Value: 0.1"]


def test_float_services_in_the_table():
    assert SERVICES[2].arguments == "S0 = float" and SERVICES[3].arguments == "D0 = double"
    assert SERVICES[6].result == "S0 = float" and SERVICES[7].result == "D0 = double"
    assert SERVICES[52].result == "S0 = float, R1 = status"
    assert SERVICES[58].arguments == "R0 = message, D0 = double"
