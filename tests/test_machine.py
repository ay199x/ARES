# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Machine: initial state, memory map, JTAG UART, program-end rules, errors."""

import struct

import pytest

from ares.console import FINISHED_ERROR
from ares.machine import (DDR_PAGE, INITIAL_CPSR, INITIAL_SP, Machine, StopReason,
                          condition_passed)

FINISHED = "-- program is finished running --\n"
DROPPED = "-- program is finished running (dropped off bottom) --\n"


def word(machine, address):
    return struct.unpack("<I", machine.read_memory(address, 4))[0]


# Initial state ------------------------------------------------------------

def test_initial_state(build):
    machine = Machine(build("        NOP\n        .global _start\n_start:\n        B .\n"))
    assert [machine.reg(n) for n in range(13)] == [0] * 13
    assert machine.reg(14) == 0
    assert machine.reg(13) == INITIAL_SP == 0       # as in CPUlator
    assert machine.cpsr == INITIAL_CPSR == 0x1D3
    assert machine.pc == 4


def test_without_global_start_execution_starts_at_zero(build):
    machine = Machine(build("        MOV R0, #1\n_start:\n        MOV R0, #2\n        B .\n"))
    assert machine.pc == 0
    machine.run(time_limit=10)
    assert machine.reg(0) == 2


# The stack: SP starts at 0, so a push before the program sets SP wraps
# around to the top of the on-chip memory, and the pop wraps back to 0.
LEAF = """\
        .global _start
_start: MOV     R4, #7
        BL      leaf
        B       .
leaf:   PUSH    {R4, LR}
        MOV     R4, #9
        POP     {R4, PC}
"""
LEAF_BODY = 0x10        # MOV R4, #9: the push has run


def test_the_first_push_stores_at_the_top_of_on_chip_memory(build):
    machine = Machine(build(LEAF))
    machine.set_breakpoint(LEAF_BODY)
    assert machine.run(time_limit=10) is None and machine.at_breakpoint
    assert machine.reg(13) == 0xFFFFFFF8
    assert word(machine, 0xFFFFFFFC) == 8                   # LR: the address after BL
    assert word(machine, 0xFFFFFFF8) == 7                   # R4
    machine.set_breakpoint(LEAF_BODY, False)
    assert machine.run(time_limit=10) is StopReason.SELF_BRANCH
    assert machine.reg(13) == 0 and machine.reg(4) == 7 and machine.pc == 8


def test_backstep_undoes_a_push_and_a_pop_at_the_top_of_memory(build):
    machine = Machine(build(LEAF))
    old = bytes(range(1, 17))
    machine.write_memory(0xFFFFFFF0, old)                   # what the push replaces
    for _ in range(3):                                      # MOV, BL, PUSH
        machine.step()
    assert machine.reg(13) == 0xFFFFFFF8
    assert machine.read_memory(0xFFFFFFF0, 16) == old[:8] + struct.pack("<II", 7, 8)
    machine.step()                                          # MOV R4, #9
    machine.step()                                          # POP {R4, PC}
    assert machine.reg(13) == 0 and machine.reg(4) == 7 and machine.pc == 8
    assert machine.backstep()                               # the pop
    assert machine.reg(13) == 0xFFFFFFF8 and machine.reg(4) == 9 and machine.pc == 0x14
    assert machine.backstep() and machine.backstep()        # MOV, then the push
    assert machine.reg(13) == 0 and machine.reg(4) == 7 and machine.pc == 0xC
    assert machine.read_memory(0xFFFFFFF0, 16) == old


def test_a_stack_larger_than_the_on_chip_memory_stops_the_program(run):
    machine = run(".global _start\n_start: PUSH {R0}\n        B _start\n")
    assert machine.error == ("Runtime error at line 2 (address 0x00000000): "
                             "memory access out of range at 0xfffefffc")
    assert machine.reg(13) == 0xFFFF0000                    # 64 KB pushed


def test_reset_empties_the_stack(build):
    machine = Machine(build(LEAF))
    for _ in range(3):                                      # MOV, BL, PUSH
        machine.step()
    machine.reset()
    assert machine.reg(13) == 0 and machine.read_memory(0xFFFFFFF8, 8) == bytes(8)


def test_a_program_may_put_its_stack_at_the_top_of_ddr3(run):
    machine = run("        .global _start\n_start:\n        LDR SP, =0x40000000\n"
                  "        MOV R1, #5\n        PUSH {R1}\n        B .\n")
    assert machine.reg(13) == 0x3FFFFFFC
    assert word(machine, 0x3FFFFFFC) == 5


def test_floating_point_unit_enabled(run):
    machine = run("""\
        .global _start
_start:
        LDR     R1, =0x3F800000     @ 1.0
        VMOV    S0, R1
        VADD.F32 S1, S0, S0
        VMOV    R2, S1
        B       .
""")
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert machine.reg(2) == 0x40000000     # 2.0


def test_vfp_registers(run):
    machine = run("""\
        .global _start
_start:
        LDR     R1, =0x3FC00000     @ 1.5
        VMOV    S0, R1
        VADD.F32 S1, S0, S0         @ 3.0
        VCVT.F64.F32 D2, S1
        VCMP.F32 S0, S1             @ less than: N
        VMRS    APSR_nzcv, FPSCR
        B       .
""")
    doubles, fpscr = machine.vfp()
    assert len(doubles) == 32
    assert doubles[0] == 0x404000003FC00000          # S1:S0
    assert doubles[2] == 0x4008000000000000          # 3.0
    assert fpscr == 0x80000000 and machine.cpsr >> 28 == 0b1000


def test_vfp_registers_start_at_zero_and_can_be_set(build):
    machine = Machine(build("        .global _start\n_start: B .\n"))
    assert machine.vfp() == ([0] * 32, 0)
    machine.set_single(3, 0xBF800000)                # S3: the high half of D1
    machine.set_double(2, 0x4008000000000000)
    machine.set_single(4, 0x12345678)                # S4: the low half of D2
    machine.set_fpscr_flag(30, 1)                    # Z
    doubles, fpscr = machine.vfp()
    assert doubles[1] == 0xBF80000000000000
    assert doubles[2] == 0x4008000012345678
    assert fpscr == 0x40000000
    machine.set_fpscr_flag(30, 0)
    assert machine.vfp()[1] == 0
    machine.reset()
    assert machine.vfp() == ([0] * 32, 0)


def test_spsr_is_the_current_mode_s(build):
    machine = Machine(build("""\
        .global _start
_start: MSR     SPSR_fsxc, #0x10    @ the SPSR of Supervisor mode
        CPS     #0x12               @ IRQ mode: an SPSR of its own
        MRS     R1, SPSR
        CPS     #0x13
        B       .
"""))
    assert machine.spsr == 0
    machine.step()
    assert machine.spsr == 0x10
    machine.step()
    assert machine.cpsr & 0x1F == 0x12 and machine.spsr == 0
    machine.set_spsr_flag(31, 1)
    assert machine.spsr == 0x80000000
    machine.step()
    assert machine.reg(1) == 0x80000000                 # the program reads what was set
    machine.step()
    assert machine.spsr == 0x10                         # Supervisor mode's again
    machine.set_spsr_flag(4, 0)
    assert machine.spsr == 0


def test_backstep_restores_fpexc(build):
    machine = Machine(build("""\
        .global _start
_start: VMOV.F32 S0, #1.0
        VMRS    R0, FPEXC
        BIC     R1, R0, #0x40000000     @ the VFP off
        VMSR    FPEXC, R1
        B       .
"""))
    for _ in range(4):
        machine.step()
    for _ in range(4):
        machine.backstep()
    assert machine.pc == 0
    assert machine.step() is None and machine.single(0) == 0x3F800000     # the VFP is on again


def test_backstep_restores_the_spsr(build):
    machine = Machine(build("""\
        .global _start
_start: MSR     SPSR_fsxc, #0x10
        CPS     #0x12
        MSR     SPSR_fsxc, #0x1F
        B       .
"""))
    for _ in range(3):
        machine.step()
    assert machine.spsr == 0x1F and machine.cpsr & 0x1F == 0x12
    machine.backstep()
    assert machine.spsr == 0 and machine.cpsr & 0x1F == 0x12     # IRQ mode's SPSR again
    machine.backstep()
    assert machine.cpsr & 0x1F == 0x13 and machine.spsr == 0x10
    machine.backstep()
    assert machine.spsr == 0


def test_reset_restores_program_and_state(run):
    machine = run("""\
        .global _start
_start:
        LDR     R1, =value
        MOV     R2, #9
        STR     R2, [R1]
        B       .
        .data
value:  .word   3
""")
    address = machine.program.label_address("value")
    assert word(machine, address) == 9
    machine.reset()
    assert word(machine, address) == 3
    assert machine.reg(1) == 0 and machine.pc == 0
    assert machine.stop_reason is None


# Memory map ---------------------------------------------------------------

def test_ddr_mapped_on_first_access(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =0x20000004
        LDR     R1, =0xCAFEF00D
        STR     R1, [R0]
        LDR     R2, [R0]
        LDR     R3, =0x3FF00000
        LDR     R4, [R3]
        B       .
""")
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert machine.reg(2) == 0xCAFEF00D
    assert machine.reg(4) == 0
    assert {0x20000000 // DDR_PAGE, 0x3FF00000 // DDR_PAGE} <= machine._ddr_pages
    assert machine.read_memory(0x10000000, 8) == bytes(8)      # never touched


def test_onchip_memory(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =0xFFFFFFFC
        MOV     R1, #77
        STR     R1, [R0]
        LDR     R2, [R0]
        B       .
""")
    assert machine.reg(2) == 77


@pytest.mark.parametrize("address", [0x40000000, 0x80000000, 0xFF1FFFFC, 0xFF210000,
                                     0xFFFEFFFC])
def test_access_outside_memory_map_stops(run, address):
    machine = run(f"""\
        .global _start
_start:
        LDR     R0, =0x{address:08X}
        MOV     R5, #1
        LDR     R1, [R0]
        MOV     R5, #2
        B       .
""")
    assert machine.stop_reason is StopReason.ERROR
    message = (f"Runtime error at line 5 (address 0x00000008): "
               f"memory access out of range at 0x{address:08x}")
    assert machine.error == message
    assert machine.console.text == message + "\n" + FINISHED_ERROR + "\n"
    assert machine.pc == 8
    assert machine.reg(5) == 1


DEVICE_WARNING = ("Warning: DE1-SoC device at 0x{:08x} is not simulated: "
                  "writes are ignored, reads return 0")


def test_other_devices_ignore_writes_and_read_zero(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =0xFF200000     @ red LEDs
        MOV     R1, #0x3FF
        STR     R1, [R0]
        LDR     R2, [R0]
        LDR     R3, =0xFF200040     @ slider switches
        MVN     R4, #0
        LDR     R4, [R3]
        STR     R1, [R0]            @ same address again: no second warning
        LDRB    R5, [R3, #1]
        LDR     R6, =0xFF20FFFC     @ last word of the device region
        STR     R1, [R6]
        MOV     R7, #7
        B       .
""")
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert (machine.reg(2), machine.reg(4), machine.reg(5), machine.reg(7)) == (0, 0, 0, 7)
    assert machine.warnings == [DEVICE_WARNING.format(a) for a in
                                (0xFF200000, 0xFF200040, 0xFF200041, 0xFF20FFFC)]
    assert machine.console.text == FINISHED


def test_device_next_to_jtag_uart_is_not_simulated(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =0xFF201000
        MOV     R1, #65
        STR     R1, [R0, #8]        @ second JTAG UART: not simulated
        STRB    R1, [R0]
        B       .
""")
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert machine.warnings == [DEVICE_WARNING.format(0xFF201008)]
    assert machine.console.text == "A\n" + FINISHED


def test_device_warnings_taken_once_and_cleared_by_reset(run):
    machine = run("        .global _start\n_start:\n        LDR R0, =0xFF200020\n"
                  "        STR R0, [R0]\n        B .\n")
    assert machine.take_warnings() == [DEVICE_WARNING.format(0xFF200020)]
    assert machine.take_warnings() == []
    machine.reset()
    assert machine.warnings == []
    machine.run(time_limit=10)
    assert machine.take_warnings() == [DEVICE_WARNING.format(0xFF200020)]


def test_jump_to_address_without_code_stops(run):
    machine = run("        .global _start\n_start:\n        LDR R0, =0x30000000\n"
                  "        BX R0\n")
    assert machine.error == ("Runtime error at address 0x30000000: "
                             "no program code at 0x30000000")
    assert machine.error_address == 0x30000000


def run_to_the_end(machine, how):
    """Go, Step after Step, or slices recorded for Backstep (Enable Backstep While Running)."""
    if how == "go":
        machine.run(time_limit=10)
    elif how == "step":
        while machine.step() is None:
            pass
    else:
        while machine.run_slice(record=True) is None:
            pass


# The DE1-SoC devices' registers hold no program, like DDR3 never written and
# addresses outside the memory map; a BX to an odd address runs Thumb code at
# the even one.
@pytest.mark.parametrize("target", [0xFF200000, 0xFF201000, 0xFF20FFFC, 0xFF200001,
                                    0x30000000, 0x50000000], ids=hex)
@pytest.mark.parametrize("how", ["go", "step", "recorded"])
def test_a_jump_where_there_is_no_program_code_stops(build, target, how):
    machine = Machine(build(f"        .global _start\n_start:\n        LDR R0, =0x{target:08X}\n"
                            "        BX R0\n"))
    run_to_the_end(machine, how)
    address = target & ~1
    message = f"Runtime error at address 0x{address:08x}: no program code at 0x{address:08x}"
    assert machine.stop_reason is StopReason.ERROR and machine.error == message
    assert machine.console.text == message + "\n" + FINISHED_ERROR + "\n"
    assert machine.pc == machine.error_address == address


def test_the_failing_instruction_is_kept_until_backstep_or_reset(build):
    machine = Machine(build("        .global _start\n_start:\n        MOV R0, #0x50000000\n"
                            "        LDR R1, [R0]\n        SVC #10\n"))
    assert machine.error_address is None
    run_to_the_end(machine, "step")
    assert machine.error_address == machine.pc == 4
    machine.set_reg(15, 8)              # PC changed afterwards: the failure stays where it was
    assert machine.error_address == 4
    assert machine.backstep() and machine.error_address is None and machine.pc == 0
    run_to_the_end(machine, "go")
    assert machine.error_address == 4
    machine.reset()
    assert machine.error_address is None


def test_undefined_instruction_stops(run):
    machine = run("        .global _start\n_start:\n        NOP\n        UDF #0\n        B .\n")
    assert machine.error == ("Runtime error at line 4 (address 0x00000004): "
                             "undefined instruction")


# JTAG UART ----------------------------------------------------------------

def test_jtag_uart_output_byte_and_word(run):
    machine = run("""\
        .global _start
_start:
        LDR     R1, =0xFF201000
        MOV     R0, #'A'
        STRB    R0, [R1]
        LDR     R0, =0x12345642     @ only the low byte is output
        STR     R0, [R1]
        B       .
""")
    assert machine.console.text == "AB\n" + FINISHED


def test_jtag_uart_control_register(run):
    machine = run("        .global _start\n_start:\n        LDR R1, =0xFF201000\n"
                  "        LDR R0, [R1, #4]\n        STR R0, [R1, #4]\n        B .\n")
    assert machine.reg(0) == 64 << 16
    assert machine.console.text == FINISHED


def test_jtag_uart_input(run):
    machine = run("""\
        .global _start
_start:
        LDR     R1, =0xFF201000
        LDR     R2, [R1]
        LDR     R3, [R1]
        LDR     R4, [R1]
        B       .
""", input_text="ab")
    assert machine.reg(2) == (1 << 16) | 0x8000 | ord("a")
    assert machine.reg(3) == 0x8000 | ord("b")
    assert machine.reg(4) == 0


def test_peek_words_reads_memory_without_side_effects(build):
    machine = Machine(build("""\
        .global _start
_start: MOV     R0, #1
        B       .
        .data
value:  .word   0x11223344, 7
"""))
    value = machine.program.label_address("value")
    pages = set(machine._ddr_pages)
    assert machine.peek_words(0, 2) == [0xE3A00001, 0xEAFFFFFE]
    assert machine.peek_words(value, 3) == [0x11223344, 7, 0]
    assert machine.peek_words(0x20000000, 2) == [0, 0]      # never touched: zeros
    assert machine._ddr_pages == pages                      # and still not mapped
    assert machine.peek_words(0x3FFFFFF8, 4) == [0, 0, None, None]
    assert machine.peek_words(0xFFFF0000, 1) == [0]         # on-chip memory


def test_peek_words_of_the_devices_take_no_input_and_give_no_warning(build):
    machine = Machine(build(".global _start\n_start: B .\n"))
    machine.console.feed("ab")
    words = machine.peek_words(0xFF201000, 4)
    assert words == [(1 << 16) | 0x8000 | ord("a"), 64 << 16, 0, 0]
    assert machine.peek_words(0xFF201000, 1) == words[:1]
    assert machine.console.pending() == 2
    assert machine.peek_words(0xFF200000, 1) == [0] and machine.take_warnings() == []
    machine.console.read_byte()
    machine.console.read_byte()
    assert machine.peek_words(0xFF201000, 1) == [0]


def test_close_and_reset_give_back_the_emulator_memory(build):
    machine = Machine(build(".global _start\n_start: B .\n"))
    old = machine.uc
    assert list(old.mem_regions())
    machine.reset()
    assert list(old.mem_regions()) == [] and list(machine.uc.mem_regions())
    machine.close()
    assert list(machine.uc.mem_regions()) == []


LOOP = """\
        .global _start
_start: MOV     R0, #0
loop:   ADD     R0, R0, #1
        ADD     R1, R1, #2
        B       loop
"""


def test_a_breakpoint_set_after_its_code_ran_stops_a_run(build):
    from conftest import PROGRAMS
    machine = Machine(build((PROGRAMS / "fact.s").read_text()))
    for _ in range(3):                              # MOV, BL, then PUSH at 0x18 runs
        machine.step()
    machine.set_breakpoint(0x18)                    # the recursive call comes back to it
    assert machine.run(time_limit=5) is None
    assert machine.at_breakpoint and machine.pc == 0x18


def test_recording_after_a_fast_run_records_every_instruction(build):
    machine = Machine(build(LOOP))
    machine.run_slice(timeout_ms=2)
    count = machine.reg(0)
    machine.run_slice(timeout_ms=2, record=True)
    # Three instructions a round; a slice starting or stopping within a round
    # does up to two instructions fewer than this.
    done = (machine.reg(0) - count) * 3
    assert len(machine.history) >= min(done - 2, 1900)
    r0 = machine.reg(0)
    machine.backstep()
    assert machine.reg(0) in (r0, r0 - 1) and machine.pc in (0x4, 0x8, 0xC)


def test_backstep_undoes_a_store_that_wraps_to_address_zero(build):
    machine = Machine(build(".global _start\n_start: MOV R1, #0\n        MOV R0, #0x700\n"
                            "        STRH R0, [R1, #-1]\n        SVC #10\n"))
    before = machine.read_memory(0xFFFFFFFF, 2)
    for _ in range(3):
        machine.step()
    assert machine.read_memory(0xFFFFFFFF, 2) == b"\x00\x07" != before
    assert machine.backstep()
    assert machine.pc == 8 and machine.read_memory(0xFFFFFFFF, 2) == before
    assert len(machine.history) == 2


def test_a_system_call_write_wraps_to_address_zero(build):
    machine = Machine(build(".global _start\n_start: MVN R0, #3\n        MOV R1, #8\n"
                            "        SVC #8\n        SVC #10\n"))
    before = machine.read_memory(0xFFFFFFFC, 5)
    machine.console.feed("abc\n")
    for _ in range(3):
        machine.step()
    assert machine.error is None and machine.read_memory(0xFFFFFFFC, 5) == b"abc\n\x00"
    assert machine.backstep() and machine.read_memory(0xFFFFFFFC, 5) == before


def test_drop_request_forgets_a_waiting_service(build):
    machine = Machine(build(".global _start\n_start: SVC #5\n        SVC #10\n"))
    machine.run_slice()
    assert machine.request is not None
    machine.drop_request()
    assert machine.request is None and machine.request_done()


# How a program ends -------------------------------------------------------

def test_branch_to_itself_ends_program(run):
    machine = run("        .global _start\n_start:\n        MOV R0, #1\n        B .\n")
    assert machine.stop_reason is StopReason.SELF_BRANCH
    assert machine.console.text == FINISHED
    assert machine.pc == 4


def test_conditional_branch_to_itself_not_taken_continues(run):
    machine = run("""\
        .global _start
_start:
        MOVS    R0, #1          @ Z clear
        BEQ     .
        MOV     R1, #7
        B       .
""")
    assert machine.reg(1) == 7
    assert machine.pc == 12


def test_dropping_off_the_bottom(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =0x11111111
        MOV     R1, #2
        .data
value:  .word   0
""")
    assert machine.stop_reason is StopReason.DROPPED_OFF
    assert machine.console.text == DROPPED
    assert machine.reg(1) == 2
    assert machine.pc == 8          # the literal pool is not executed


def test_branch_to_end_address_drops_off(run):
    machine = run("""\
        .global _start
_start:
        MOV     R0, #1
        B       after
        MOV     R0, #2
after:
""")
    assert machine.stop_reason is StopReason.DROPPED_OFF
    assert machine.reg(0) == 1


def test_long_running_program_runs_in_slices(run):
    machine = run("""\
        .global _start
_start:
        LDR     R0, =20000000
loop:   SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
""")
    assert machine.stop_reason is StopReason.EXIT
    assert machine.reg(0) == 0


@pytest.mark.parametrize("cond, flags, expected", [
    (0x0, 0x4, True), (0x0, 0x0, False),            # EQ
    (0x1, 0x0, True),                               # NE
    (0x2, 0x2, True), (0x3, 0x2, False),            # CS, CC
    (0x4, 0x8, True), (0x5, 0x8, False),            # MI, PL
    (0x6, 0x1, True), (0x7, 0x1, False),            # VS, VC
    (0x8, 0x2, True), (0x8, 0x6, False),            # HI
    (0x9, 0x4, True),                               # LS
    (0xA, 0x9, True), (0xB, 0x8, True),             # GE, LT
    (0xC, 0x0, True), (0xC, 0x4, False),            # GT
    (0xD, 0x4, True),                               # LE
    (0xE, 0x0, True),                               # AL
])
def test_condition_passed(cond, flags, expected):
    assert condition_passed(cond, flags << 28) == expected
