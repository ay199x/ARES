# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Runner: Go, Step, Backstep, breakpoints, Pause, Stop, Reset, waiting."""

import gc
import threading
import time

import pytest

from ares.machine import (DIALOG, HISTORY_LIMIT, INPUT, SNAPSHOT_REGISTERS, Machine,
                          StopReason)
from ares.runner import State
from ares.syscalls import INPUT_INTEGER

LOOP = """\
        .global _start
_start:
        MOV     R0, #0
loop:   ADD     R0, R0, #1
        ADD     R1, R1, #2
        B       loop
"""

# Changes registers, flags, VFP registers, the stack, data in the program's
# page and in a DDR3 page that was never used, and memory written by a service.
CHANGES = """\
        .global _start
_start:
        LDR     R1, =value
        MOV     R2, #9
        MOVS    R3, #0
        STR     R2, [R1]
        STRB    R2, [R1, #5]
        PUSH    {R1, R2}
        LDR     R4, =0x20000000
        STR     R2, [R4, #-4]
        VMOV    S0, R2
        VCVT.F32.S32 S1, S0
        ADDS    R5, R2, R2
        LDR     R0, =buffer
        MOV     R1, #8
        SVC     #8
        MOV     R0, #42
        SVC     #1
        SVC     #10
        .data
value:  .word   3, 4
buffer: .space  8
"""


def state(machine):
    """Registers (with flags and VFP) and the memory CHANGES touches."""
    value = machine.program.label_address("value")
    return (machine.uc.reg_read_batch(SNAPSHOT_REGISTERS),
            machine.read_memory(value, 16),
            machine.read_memory(0xFFFFFFF0, 16),        # the stack
            machine.read_memory(0x1FFFFFF0, 16))


def address_of_line(machine, line):
    return next(a for a, n in machine.program.lines.items() if n == line)


# Step and Backstep --------------------------------------------------------

def test_step_executes_one_instruction(make_runner):
    runner = make_runner(LOOP)
    assert runner.state is State.READY
    assert runner.step() is State.PAUSED
    assert runner.machine.pc == 4 and runner.machine.reg(0) == 0
    runner.step()
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 1


def test_step_backstep_round_trip_restores_everything(make_runner):
    runner = make_runner(CHANGES, input_text="hello\n")
    machine = runner.machine
    before = []
    while runner.state is not State.FINISHED:
        before.append(state(machine))
        runner.step()
    assert machine.console.text == "42\n-- program is finished running --\n"
    assert machine.read_memory(machine.program.label_address("buffer"), 8) == b"hello\n\0\0"
    for expected in reversed(before):
        assert runner.backstep()
        assert state(machine) == expected
    assert not runner.backstep()
    assert machine.pc == 0 and runner.state is State.PAUSED


def test_backstep_after_the_end_continues_the_program(make_runner):
    runner = make_runner("        .global _start\n_start:\n        MOV R0, #1\n"
                         "        SVC #10\n")
    runner.step()
    assert runner.step() is State.FINISHED
    assert runner.backstep()
    assert runner.state is State.PAUSED and runner.machine.stop_reason is None
    assert runner.machine.pc == 4
    assert runner.run() is State.FINISHED


def test_backstep_after_a_runtime_error(make_runner):
    runner = make_runner("""\
        .global _start
_start:
        MOV     R5, #1
        LDR     R0, =0x50000000
        LDR     R1, [R0]
        B       .
""")
    runner.step()
    runner.step()
    assert runner.step() is State.FINISHED
    assert runner.machine.stop_reason is StopReason.ERROR
    assert runner.backstep()                    # undoes the LDR R0 before the error
    assert runner.machine.error is None
    assert runner.machine.pc == 4 and runner.machine.reg(0) == 0
    assert runner.machine.reg(5) == 1


def test_history_keeps_the_last_2000_steps(make_runner):
    runner = make_runner(LOOP)
    for _ in range(HISTORY_LIMIT + 100):
        runner.step()
    count = 0
    while runner.backstep():
        count += 1
    assert count == HISTORY_LIMIT == 2000
    # back to the state after 100 steps: MOV, then 33 rounds of the 3-instruction loop
    assert (runner.machine.pc, runner.machine.reg(0)) == (4, 33)


def test_full_speed_go_records_nothing(make_runner):
    runner = make_runner(CHANGES, input_text="hi\n")
    assert runner.run() is State.FINISHED
    assert not runner.backstep()


def test_go_with_backstep_while_running(make_runner):
    runner = make_runner(CHANGES, input_text="hello\n", record_while_running=True)
    initial = state(runner.machine)
    assert runner.run() is State.FINISHED
    while runner.backstep():
        pass
    assert state(runner.machine) == initial


# Breakpoints ----------------------------------------------------------------

def test_breakpoint_stops_before_the_instruction(make_runner):
    runner = make_runner(LOOP)
    runner.set_breakpoint(8)                    # ADD R1, R1, #2
    assert runner.run() is State.PAUSED
    machine = runner.machine
    assert machine.at_breakpoint
    assert (machine.pc, machine.reg(0), machine.reg(1)) == (8, 1, 0)
    assert runner.run() is State.PAUSED        # goes on from the breakpoint
    assert (machine.pc, machine.reg(0), machine.reg(1)) == (8, 2, 2)


def test_step_from_a_breakpoint_executes_it(make_runner):
    runner = make_runner(LOOP)
    runner.set_breakpoint(4)
    runner.run()
    assert runner.machine.pc == 4
    runner.step()
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 1


def test_breakpoint_set_after_the_code_ran(make_runner):
    runner = make_runner(LOOP)
    assert runner.run(time_limit=0.05) is State.PAUSED
    count, paused_at = runner.machine.reg(0), runner.machine.pc
    assert count > 1000
    runner.set_breakpoint(4)
    runner.run()
    # Go from 4 itself executes that ADD first; from 8 or 12 the loop reaches 4 first.
    assert runner.machine.pc == 4
    assert runner.machine.reg(0) == count + (paused_at == 4)
    runner.toggle_breakpoint(4)
    assert runner.machine.breakpoints == set()
    assert runner.run(time_limit=0.05) is State.PAUSED
    assert runner.machine.reg(0) > count + 1000


def test_breakpoints_survive_reset(make_runner):
    runner = make_runner(LOOP)
    runner.set_breakpoint(8)
    runner.run()
    runner.reset()
    assert runner.state is State.READY and runner.machine.breakpoints == {8}
    runner.run()
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 1


def test_slow_go_runs_one_recorded_instruction_per_slice(make_runner):
    runner = make_runner(LOOP)
    runner.set_breakpoint(12)                   # B loop
    runner.go(slow=True)
    states = [runner.run_slice() for _ in range(4)]
    assert states == [State.RUNNING, State.RUNNING, State.RUNNING, State.PAUSED]
    assert runner.machine.pc == 12
    assert len(runner.machine.history) == 3
    runner.go(slow=True)
    assert runner.run_slice() is State.RUNNING  # leaves the breakpoint
    assert runner.machine.pc == 4


# Pause, Stop, Reset ---------------------------------------------------------

# Loops whose instructions cost Python time: system calls (a file open and
# close each round) and recording every instruction for Backstep.
SERVICE_LOOP = """\
        .global _start
_start:
loop:   LDR     R0, =name
        MOV     R1, #9
        SVC     #13
        SVC     #16
        B       loop
        .data
name:   .asciz  "app.txt"
"""
BUSY = [(LOOP, False), (SERVICE_LOOP, False), (LOOP, True)]


@pytest.fixture
def quiet_gc():
    """Time ARES, not the test run: late in a full run, every garbage
    collection the program's run sets off walks all the objects earlier tests
    left behind, which can take longer than the times measured here."""
    gc.collect()
    gc.freeze()
    yield
    gc.unfreeze()


@pytest.mark.serial
@pytest.mark.parametrize("source, record", BUSY, ids=["alu", "services", "recording"])
@pytest.mark.parametrize("command, final", [("pause", State.PAUSED), ("stop", State.FINISHED)])
def test_pause_and_stop_take_effect_within_100_ms(make_runner, quiet_gc, source, record, command,
                                                   final):
    runner = make_runner(source, record_while_running=record)
    thread = threading.Thread(target=runner.run)
    thread.start()
    time.sleep(0.2)
    assert runner.state is State.RUNNING
    start = time.perf_counter()
    getattr(runner, command)()
    thread.join(timeout=5)
    elapsed = time.perf_counter() - start
    assert not thread.is_alive()
    assert runner.state is final
    assert elapsed < 0.1


@pytest.mark.serial
@pytest.mark.parametrize("source, record", BUSY, ids=["alu", "services", "recording"])
def test_a_slice_lasts_about_30_ms(build, tmp_path, quiet_gc, source, record):
    machine = Machine(build(source), base_dir=tmp_path)
    times = []
    for _ in range(5):
        start = time.perf_counter()
        assert machine.run_slice(record=record) is None
        times.append(time.perf_counter() - start)
    assert min(times) < 0.06, times


def test_stop_cannot_be_continued_but_reset_can(make_runner):
    runner = make_runner(LOOP)
    runner.run(time_limit=0.05)
    runner.stop()
    assert runner.state is State.FINISHED and runner.stopped_by_user
    runner.go()
    assert runner.state is State.FINISHED
    runner.reset()
    assert runner.state is State.READY and not runner.stopped_by_user
    assert runner.machine.pc == 0 and runner.machine.reg(0) == 0


def test_reset_restores_memory(make_runner):
    runner = make_runner(CHANGES, input_text="hello\n")
    initial = state(runner.machine)
    runner.run()
    assert state(runner.machine) != initial
    runner.reset()
    assert state(runner.machine)[1:] == initial[1:]


# Waiting for input, dialogs and time ---------------------------------------

READ_AND_PRINT = """\
        .global _start
_start:
        MOV     R4, #7
        SVC     #5
        SVC     #1
        MOV     R0, #10
        SVC     #11
        B       .
"""


def test_go_waits_for_a_typed_line(make_runner):
    runner = make_runner(READ_AND_PRINT)
    machine = runner.machine
    assert runner.run() is State.WAITING
    assert runner.request.kind == INPUT and runner.request.service == 5
    assert machine.pc == 4                      # the SVC runs again once input is there
    machine.console.feed("12")
    assert runner.run_slice() is State.WAITING  # no Enter yet
    machine.console.feed("3\n")
    assert runner.run() is State.FINISHED
    assert machine.console.text == "123\n-- program is finished running --\n"


def test_step_waits_for_a_typed_line(make_runner):
    runner = make_runner(READ_AND_PRINT)
    runner.step()
    assert runner.step() is State.WAITING
    assert runner.machine.pc == 4
    runner.machine.console.feed("-5\n")
    assert runner.run_slice() is State.PAUSED
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 0xFFFFFFFB
    assert runner.backstep() and runner.machine.pc == 4
    assert runner.machine.reg(0) == 0


def test_pause_while_waiting(make_runner):
    runner = make_runner(READ_AND_PRINT)
    runner.run()
    runner.pause()
    assert runner.state is State.PAUSED and runner.request is None
    runner.go()
    assert runner.run_slice() is State.WAITING


INPUT_DIALOG = """\
        .global _start
_start:
        LDR     R0, =prompt
        SVC     #51
        SVC     #1
        B       .
        .data
prompt: .asciz  "Number?"
"""


def test_dialog_answered_by_the_window(make_runner):
    runner = make_runner(INPUT_DIALOG)
    assert runner.run() is State.WAITING
    request = runner.request
    assert (request.kind, request.service, request.dialog, request.message) == (
        DIALOG, 51, INPUT_INTEGER, "Number?")
    runner.answer("77")
    assert runner.run() is State.FINISHED
    assert runner.machine.console.text.startswith("77\n")


def test_dialog_answered_by_a_handler(make_runner):
    asked = []
    runner = make_runner(INPUT_DIALOG, dialogs=lambda r: asked.append(r) or "-3")
    assert runner.step() is State.PAUSED
    assert runner.step() is State.PAUSED        # the handler answered at once
    assert [r.message for r in asked] == ["Number?"]
    assert runner.machine.reg(0) == 0xFFFFFFFD and runner.machine.reg(1) == 0


def test_input_source_supplies_lines(build):
    from ares.machine import Machine
    from ares.runner import Runner
    lines = iter([b"5\n"])
    machine = Machine(build(READ_AND_PRINT))
    runner = Runner(machine, input_source=lambda request: next(lines, None))
    assert runner.run() is State.FINISHED
    assert machine.console.text.startswith("5\n")


SLEEP = """\
        .global _start
_start:
        MOV     R0, #400
        SVC     #32
        MOV     R1, #1
        B       .
"""


@pytest.mark.serial
def test_sleep_pauses_a_go_without_blocking(make_runner):
    runner = make_runner(SLEEP)
    runner.go()
    start = time.perf_counter()
    runner.run_slice()
    assert runner.state is State.RUNNING and 0 < runner.sleep_remaining() <= 0.4
    assert runner.run_slice() is State.RUNNING  # returns at once while asleep
    assert time.perf_counter() - start < 0.2
    assert runner.run() is State.FINISHED
    assert time.perf_counter() - start >= 0.4
    assert runner.machine.reg(1) == 1


@pytest.mark.serial
def test_step_does_not_wait_for_a_sleep(make_runner):
    runner = make_runner(SLEEP)
    runner.step()
    start = time.perf_counter()
    runner.step()
    runner.step()
    assert time.perf_counter() - start < 0.2
    assert runner.machine.reg(1) == 1


# Regressions -----------------------------------------------------------------

JTAG_PRINT = """\
        .global _start
_start:
        LDR     R9, =0xFF201000
        LDR     R8, =200000
loop:   AND     R1, R8, #7
        ADD     R1, R1, #'a'
        STR     R1, [R9]
        SUBS    R8, R8, #1
        BNE     loop
        SVC     #10
"""


def test_jtag_output_is_exact_across_many_slices(make_runner):
    runner = make_runner(JTAG_PRINT)
    assert runner.run() is State.FINISHED
    expected = "".join(chr(ord("a") + (n & 7)) for n in range(200000, 0, -1))
    assert runner.machine.console.text == expected + "\n-- program is finished running --\n"


def test_jtag_input_is_exact_across_many_slices(make_runner):
    runner = make_runner("""\
        .global _start
_start:
        LDR     R1, =0xFF201000
        MOV     R4, #0
wait:   LDR     R0, [R1]
        TST     R0, #0x8000
        BEQ     wait
        AND     R0, R0, #0xFF
        CMP     R0, #'#'
        ADDNE   R4, R4, #1
        BNE     wait
        MOV     R0, R4
        SVC     #1
        SVC     #10
""", input_text="x" * 150000 + "#")
    assert runner.run() is State.FINISHED
    assert runner.machine.console.text.startswith("150000\n")


def test_full_speed_go_clears_the_history(make_runner):
    runner = make_runner(LOOP)
    runner.step()
    runner.step()
    runner.run(time_limit=0.02)
    assert not runner.backstep()


SLEEP_THEN_BREAKPOINT = """\
        .global _start
_start:
        MOV     R0, #50
        SVC     #32
        MOV     R1, #1
        MOV     R2, #2
        B       .
"""


@pytest.mark.parametrize("slow", [False, True])
def test_breakpoint_right_after_a_sleep(make_runner, slow):
    runner = make_runner(SLEEP_THEN_BREAKPOINT)
    runner.set_breakpoint(8)
    runner.go(slow=slow)
    while runner.run_slice() is State.RUNNING:
        time.sleep(0.005)
    assert runner.state is State.PAUSED
    assert runner.machine.pc == 8 and runner.machine.reg(1) == 0


def test_slow_go_does_not_stop_twice_at_a_waiting_svc(make_runner):
    runner = make_runner(READ_AND_PRINT)
    runner.set_breakpoint(4)                    # the SVC #5 that waits
    runner.go(slow=True)
    states = [runner.run_slice() for _ in range(2)]
    assert states == [State.RUNNING, State.PAUSED]
    runner.go(slow=True)
    assert runner.run_slice() is State.WAITING
    runner.machine.console.feed("8\n")
    runner.run_slice()                          # input arrives: no second stop
    assert runner.run_slice() is State.RUNNING
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 8


def test_step_after_pausing_a_sleep_executes(make_runner):
    runner = make_runner(SLEEP)
    runner.go()
    runner.run_slice()                          # now asleep after SVC #32
    runner.pause()
    assert runner.state is State.PAUSED and runner.machine.pc == 8
    runner.step()
    assert runner.machine.pc == 12 and runner.machine.reg(1) == 1


def test_backstep_after_a_jump_to_nowhere(make_runner):
    runner = make_runner("""\
        .global _start
_start:
        MOV     R5, #1
        LDR     R0, =0x30000000
        BX      R0
""")
    runner.step()
    runner.step()
    assert runner.step() is State.FINISHED
    assert runner.machine.error.endswith("no program code at 0x30000000")
    assert runner.backstep()                    # undoes BX only
    assert runner.machine.pc == 8 and runner.machine.reg(0) == 0x30000000


def test_breakpoint_on_branch_to_itself(make_runner):
    runner = make_runner("        .global _start\n_start:\n        MOV R0, #1\n        B .\n")
    runner.set_breakpoint(4)
    assert runner.run() is State.PAUSED and runner.machine.pc == 4
    assert runner.machine.stop_reason is None
    assert runner.run() is State.FINISHED       # going on from it ends the program
    assert runner.machine.stop_reason is StopReason.SELF_BRANCH


def test_stop_closes_the_program_files(make_runner, tmp_path):
    runner = make_runner("""\
        .global _start
_start:
        LDR     R0, =name
        MOV     R1, #1
        SVC     #13
        MOV     R4, R0
        LDR     R1, =name
        MOV     R2, #3
        SVC     #15
loop:   B       loop2
loop2:  B       loop
        .data
name:   .asciz  "out.txt"
""")
    runner.run(time_limit=0.05)
    assert (tmp_path / "out.txt").read_bytes() == b"out"     # written at once
    runner.stop()
    assert runner.machine.services.files == {}


def test_steps_to_the_end_record_only_executed_instructions(make_runner):
    runner = make_runner("""\
        .global _start
_start:
        MOV     R4, #4
        MOV     R0, #20
        SVC     #32
""")
    while runner.step() is not State.FINISHED:
        pass
    assert runner.machine.stop_reason is StopReason.DROPPED_OFF
    assert len(runner.machine.history) == 3
    assert runner.backstep() and runner.machine.pc == 8


def test_a_dropped_step_keeps_the_oldest_history(make_runner):
    runner = make_runner("""\
        .global _start
_start:
        LDR     R4, =2100
loop:   SUBS    R4, R4, #1
        BNE     loop
        SVC     #5
        B       .
""")
    while runner.machine.pc != 12:
        runner.step()
    assert len(runner.machine.history) == HISTORY_LIMIT
    assert runner.step() is State.WAITING       # the SVC waits: its change is dropped
    assert len(runner.machine.history) == HISTORY_LIMIT
    runner.pause()
    count = 0
    while runner.backstep():
        count += 1
    assert count == HISTORY_LIMIT


@pytest.mark.serial
def test_slow_go_lets_a_sleep_finish_before_a_breakpoint(make_runner):
    runner = make_runner(SLEEP_THEN_BREAKPOINT.replace("#50", "#200"))
    runner.set_breakpoint(8)
    runner.go(slow=True)
    runner.run_slice()                          # MOV R0
    runner.run_slice()                          # SVC #32: the sleep starts
    start = time.perf_counter()
    while runner.run_slice() is State.RUNNING:
        time.sleep(0.005)
    assert runner.state is State.PAUSED and runner.machine.pc == 8
    assert time.perf_counter() - start > 0.1    # the sleep ran out first
    assert runner.run() is State.FINISHED       # Go goes on from the breakpoint
    assert runner.machine.reg(1) == 1


@pytest.mark.parametrize("hint", ["WFE", "YIELD", "WFEEQ"])
def test_wait_hints_do_nothing(make_runner, hint):
    source = (f"        .global _start\n_start:\n        MOV R0, #1\n        {hint}\n"
              f"        MOV R7, #7\n        B .\n")
    runner = make_runner(source)
    assert runner.run() is State.FINISHED
    assert runner.machine.stop_reason is StopReason.SELF_BRANCH
    assert runner.machine.reg(7) == 7
    runner.reset()
    runner.set_breakpoint(4)
    assert runner.run() is State.PAUSED and runner.machine.pc == 4
    runner.step()
    assert runner.machine.pc == 8
    assert runner.backstep() and runner.machine.pc == 4
    runner.reset()
    runner.machine.clear_breakpoints()
    runner.record_while_running = True
    assert runner.run() is State.FINISHED
    assert len(runner.machine.history) == 3     # MOV, the hint, MOV


def test_smc_is_reported_on_its_own_line(run):
    machine = run("        .global _start\n_start:\n        MOV R0, #1\n        SMC #0\n"
                  "        B .\n")
    assert machine.error == ("Runtime error at line 4 (address 0x00000004): "
                             "secure monitor call (SMC) is not supported")
