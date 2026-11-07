# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The BHT Simulator's model: which branches it predicts, how its entries learn, and that
each branch counts once, whatever stopped the run at it."""

import threading
import time

import pytest
from test_benchmark import BENCHMARK, TOOL_SECONDS

from ares import observers
from ares.gui.tools.bht import (LOG_LIMIT, BHTModel, accuracy, is_conditional_branch,
                                log_line, outcome, transitions)
from ares.machine import CHUNK, RECORD_CHUNK, Machine, StopReason
from ares.runner import Runner, State

LOOP = """\
        .global _start
_start: LDR     R0, ={count}
loop:   SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
"""
BNE = 0x8                       # the address of BNE loop: entry 2
NESTED = """\
        .global _start
_start: MOV     R1, #3
outer:  MOV     R0, #4
inner:  SUBS    R0, R0, #1
        BNE     inner
        SUBS    R1, R1, #1
        BNE     outer
        SVC     #10
"""
INNER, OUTER = 0xC, 0x14        # entries 3 and 5
SHARED = """\
        .global _start
_start: MOV     R0, #4
loop:   CMP     R0, #100
        BEQ     done
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        SUBS    R0, R0, #1
        BNE     loop
done:   SVC     #10
"""
CONDITIONS = """\
        .global _start
_start: MOV     R0, #5
        CMP     R0, #3
        BGT     one
one:    BLT     two
two:    BEQ     three
three:  BHI     four
four:   BLS     five
five:   BCS     six
six:    SVC     #10
"""
FOREVER = """\
        .global _start
_start: MOV     R0, #0
loop:   ADD     R0, R0, #1
        CMP     R0, #0
        BNE     loop
"""
FLAGS = """\
        .global _start
_start: MOVS    R0, #0
        NOP
        CMP     R0, #1
        NOP
        SUBS    R0, R0, #1
        ADDS    R0, R0, #1
        NOP
        SVC     #10
"""


def make(build, source, record=False):
    """(machine, runner, model): source loaded, the model connected to it."""
    machine = Machine(build(source))
    model = BHTModel()
    model.connect(machine)
    return machine, Runner(machine, record_while_running=record), model


def entry(model, index):
    """(history, prediction, correct, incorrect) of an entry, as the table shows the first two."""
    incorrect, correct = model.counts[index]
    return model.history(index), model.prediction(index), correct, incorrect


def totals(model):
    """(correct, incorrect) of all the entries."""
    return tuple(sum(counts[k] for counts in model.counts) for k in (1, 0))


def outcomes(model):
    """[(address, predicted, taken)] of the log."""
    return [(branch.address, *outcome(key)) for branch, _, key in model.log]


# Which branches ------------------------------------------------------------------------

def test_only_b_with_a_condition_is_predicted(build):
    source = """\
        .global _start
_start: MOV     R0, #1
        CMP     R0, #1
        BNE     done
        BLNE    done
        BXNE    LR
        BLXNE   R1
        BGT     done
        B       next
next:   BAL     done
        MOVNE   PC, LR
        BEQ     done
done:   SVC     #10
"""
    machine, runner, model = make(build, source)
    assert sorted(model._branches) == [0x8, 0x18, 0x28]
    assert [model._branches[a].text for a in (0x8, 0x18, 0x28)] == [
        "BNE #0x2C", "BGT #0x2C", "BEQ #0x2C"]
    assert is_conditional_branch(0x1AFFFFFC) and is_conditional_branch(0xDAFFFFFC)
    assert not is_conditional_branch(0xEAFFFFFC)        # B (AL)
    assert not is_conditional_branch(0xFAFFFFFC)        # BLX to Thumb code
    assert not is_conditional_branch(0x1BFFFFFC)        # BLNE
    assert not is_conditional_branch(0x112FFF1E)        # BXNE LR


def test_taken_when_the_condition_holds_for_the_flags_it_finds(build):
    machine, runner, model = make(build, CONDITIONS)
    assert runner.run() is State.FINISHED
    # 5 - 3: GT, HI and CS hold; LT, EQ and LS do not.
    assert [taken for _, _, taken in outcomes(model)] == [True, False, False, True, False, True]


def test_the_entry_is_the_address_divided_by_4_modulo_the_entries():
    model = BHTModel()
    assert [model.index(a) for a in (0x0, 0x8, 0x3C, 0x40, 0x1C, 0x5C)] == [0, 2, 15, 0, 7, 7]
    model.configure(8, 1, False)
    assert [model.index(a) for a in (0x8, 0x28, 0x1C)] == [2, 2, 7]
    model.configure(32, 1, False)
    assert [model.index(a) for a in (0x8, 0x48, 0x88)] == [2, 18, 2]


# How the entries learn -----------------------------------------------------------------

def walk(bits, state, taken):
    """The states an entry goes through for the outcomes in taken (1: taken), and whether
    each prediction was right."""
    following, seen = transitions(bits), []
    for branch_taken in taken:
        key = state << 1 | branch_taken
        state = following[key]
        seen.append((state, outcome(key)[0] == branch_taken))
    return seen


def test_the_transitions():
    # One bit: the entry remembers the outcome and predicts it.
    assert transitions(1) == (0, 3) * 4
    # Two bits, from NT, NT predicting not taken (state 0): the second wrong prediction in a
    # row changes it, a single one does not.
    assert walk(2, 0, [1, 1, 0, 1, 0, 0]) == [
        (0b010, False), (0b111, False), (0b101, False), (0b011, True), (0b101, False),
        (0b000, False)]


def test_one_history_bit_predicts_what_the_branch_did_last(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    runner.run()
    assert model.update() and not model.update()
    # BNE: taken, taken, not taken.
    assert outcomes(model) == [(BNE, False, True), (BNE, True, True), (BNE, True, False)]
    assert entry(model, 2) == ("NT", False, 1, 2)
    assert model.executed == 3
    assert all(entry(model, i) == ("NT", False, 0, 0) for i in range(16) if i != 2)


def test_two_history_bits_change_the_prediction_after_two_wrong_ones(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    model.configure(16, 2, False)
    assert entry(model, 2) == ("NT, NT", False, 0, 0)
    runner.run()
    assert outcomes(model) == [(BNE, False, True), (BNE, False, True), (BNE, True, False)]
    assert entry(model, 2) == ("T, NT", True, 0, 3)


@pytest.mark.parametrize("bits, inner, outer", [
    (1, ("NT", False, 6, 6), ("NT", False, 1, 2)),
    (2, ("T, NT", True, 7, 5), ("T, NT", True, 0, 3)),
])
def test_nested_loops(build, bits, inner, outer):
    """The inner BNE goes taken, taken, taken, not taken three times: two bits predict it
    better than one."""
    machine, runner, model = make(build, NESTED)
    model.configure(16, bits, False)
    runner.run()
    assert entry(model, INNER >> 2) == inner and entry(model, OUTER >> 2) == outer
    assert model.executed == 15


@pytest.mark.parametrize("bits, history, correct", [(1, "T", (2, 1)), (2, "T, T", (2, 1))])
def test_initial_prediction_taken(build, bits, history, correct):
    machine, runner, model = make(build, LOOP.format(count=3))
    model.configure(16, bits, True)
    assert entry(model, 2) == (history, True, 0, 0)
    runner.run()
    assert entry(model, 2)[2:] == correct
    assert model.prediction(2) is (bits == 2)           # one wrong is enough with one bit


@pytest.mark.parametrize("entries, shared", [(16, (6, 2)), (8, (2, 6))])
def test_branches_that_share_an_entry_disturb_each_other(build, entries, shared):
    """BEQ at 0x8 is never taken and BNE at 0x28 nearly always: with 8 entries both use
    entry 2, and one bit of history is wrong about each of them."""
    machine, runner, model = make(build, SHARED)
    model.configure(entries, 1, False)
    runner.run()
    assert totals(model) == shared
    assert {index for _, index, _ in model.log} == ({2, 10} if entries == 16 else {2})


def test_accuracy_and_the_log_line(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    runner.run()
    assert accuracy(1, 2) == "33.33%" and accuracy(0, 0) == "" and accuracy(4, 0) == "100.00%"
    assert accuracy(2, 1) == "66.67%" and accuracy(0, 7) == "0.00%"
    assert [log_line(event) for event in model.log] == [
        "BNE #4 at 0x00000008, index 2: predicted not taken, was taken (incorrect)",
        "BNE #4 at 0x00000008, index 2: predicted taken, was taken (correct)",
        "BNE #4 at 0x00000008, index 2: predicted taken, was not taken (incorrect)"]


def test_the_accuracy_is_rounded_half_up():
    """As by hand, and as ARES's other tools round: Python's own rounding of 90.625 is 90.62."""
    assert [accuracy(right, 32 - right) for right in (1, 5, 29)] == ["3.13%", "15.63%", "90.63%"]
    assert accuracy(1, 159) == "0.63%" and accuracy(1, 1999) == "0.05%"


def test_the_log_keeps_the_newest_branches(build):
    machine, runner, model = make(build, LOOP.format(count=LOG_LIMIT + 5))
    runner.run()
    assert model.executed == LOG_LIMIT + 5 and len(model.log) == LOG_LIMIT
    assert outcomes(model)[-1] == (BNE, True, False)


# Each branch counts once ---------------------------------------------------------------

def test_a_breakpoint_on_the_branch(build):
    machine, runner, model = make(build, LOOP.format(count=5))
    runner.set_breakpoint(BNE)
    for done in range(5):
        assert runner.run() is State.PAUSED and machine.pc == BNE
        assert model.executed == done and model.next_branch().address == BNE
    assert runner.run() is State.FINISHED
    assert model.executed == 5 and model.next_branch() is None
    assert entry(model, 2) == ("NT", False, 3, 2)


def test_steps_onto_and_over_the_branch(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    steps = 0
    while runner.step() is not State.FINISHED:
        steps += 1
        # LDR, then SUBS and BNE three times
        assert model.executed == (steps - 1) // 2
        assert (model.next_branch() is not None) == (machine.pc == BNE)
    assert model.executed == 3 and entry(model, 2) == ("NT", False, 1, 2)


@pytest.mark.parametrize("record, chunk", [(False, CHUNK), (True, RECORD_CHUNK)])
def test_a_chunk_that_ends_at_the_branch(build, record, chunk):
    """LDR, then SUBS and BNE: the instruction after the first chunk is a BNE."""
    count = 6000
    assert chunk % 2 == 0 and 1 + 2 * count > chunk
    machine, runner, model = make(build, LOOP.format(count=count), record=record)
    assert runner.run() is State.FINISHED
    assert model.executed == count
    assert entry(model, 2) == ("NT", False, count - 2, 2)


def test_slow_runs_step_one_instruction_at_a_time(build):
    machine, runner, model = make(build, LOOP.format(count=4))
    runner.go(slow=True)
    while runner.state is State.RUNNING:
        runner.run_slice()
    assert machine.stop_reason is StopReason.EXIT
    assert model.executed == 4 and entry(model, 2) == ("NT", False, 2, 2)


def test_pause_from_another_thread(build):
    machine, runner, model = make(build, FOREVER)
    loop = machine.program.label_address("loop")
    for _ in range(3):
        timer = threading.Timer(0.05, runner.pause)
        timer.start()
        try:
            assert runner.run(time_limit=10) is State.PAUSED
        finally:
            timer.cancel()
        # Each pass through the loop adds 1 to R0, then runs BNE.
        assert model.executed == machine.reg(0) - (machine.pc != loop) > 0
        assert totals(model)[1] == 1                    # only the first BNE


def test_a_self_branch_that_ends_the_program_does_not_count(build):
    ends = ".global _start\n_start: MOVS R0, #0\n        BEQ .\n        SVC #10\n"
    machine, runner, model = make(build, ends)
    assert runner.run() is State.FINISHED and machine.stop_reason is StopReason.SELF_BRANCH
    assert model.executed == 0 and model.next_branch() is None
    goes_on = ends.replace("#0", "#1")
    machine, runner, model = make(build, goes_on)
    assert runner.run() is State.FINISHED and machine.stop_reason is StopReason.EXIT
    assert outcomes(model) == [(0x4, False, False)]


def test_a_breakpoint_on_a_self_branch_that_ends_the_program(build):
    machine, runner, model = make(build, ".global _start\n_start: MOVS R0, #0\n"
                                         "        BEQ .\n")
    runner.set_breakpoint(0x4)
    assert runner.run() is State.PAUSED and model.next_branch().address == 0x4
    assert runner.run() is State.FINISHED and machine.stop_reason is StopReason.SELF_BRANCH
    assert model.executed == 0


# What survives -------------------------------------------------------------------------

def test_backstep_reset_and_assemble_keep_what_it_learned(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    for _ in range(3):
        runner.step()                   # LDR, SUBS, BNE
    runner.backstep()                   # undone, but it was executed
    assert model.executed == 1 and machine.pc == BNE
    runner.step()
    assert model.executed == 2 and entry(model, 2) == ("T", True, 1, 1)
    runner.reset()                      # Reset (F12): a new emulator, the same table
    runner.run()
    assert model.executed == 5 and entry(model, 2) == ("NT", False, 3, 2)
    other = Machine(build(LOOP.format(count=2)))   # assembled again: the window passes it on
    model.observe(other)
    assert not machine.observers.active and other.observers.active
    Runner(other).run()
    assert model.executed == 7 and entry(model, 2) == ("NT", False, 3, 4)
    model.observe(None)                 # its file closed: still connected
    assert model.connected and not other.observers.active and model.executed == 7


def test_a_program_assembled_again_is_observed_at_its_own_branches(build):
    """Not also at the addresses of the old program's branches: there the new one has a SUBS."""
    machine, runner, model = make(build, LOOP.format(count=3))     # BNE at 0x8
    other = Machine(build(NESTED))
    model.observe(other)
    assert sorted(model._branches) == [INNER, OUTER]
    Runner(other).run()
    assert {branch.address for branch, _, _ in model.log} == {INNER, OUTER}
    assert model.executed == 15


def test_reset_and_new_settings_start_again(build):
    machine, runner, model = make(build, LOOP.format(count=3))
    runner.run()
    log = model.log
    model.reset()
    assert model.executed == 0 and not model.log and model.log is not log
    assert entry(model, 2) == ("NT", False, 0, 0) and model.connected
    runner.reset()
    runner.run()
    assert model.executed == 3
    model.configure(8, 2, True)
    assert len(model.states) == len(model.counts) == 8
    assert model.executed == 0 and not model.log
    assert entry(model, 2) == ("T, T", True, 0, 0)
    assert (model.entries, model.history_bits, model.initial) == (8, 2, True)


def test_nothing_is_observed_while_disconnected(build):
    machine = Machine(build(LOOP.format(count=3)))
    runner = Runner(machine)
    model = BHTModel()
    model.observe(machine)              # not connected: nothing hooked
    assert model.machine is None and not machine.observers.active
    runner.step()
    model.connect(machine)
    assert machine.observers.active
    runner.step()
    runner.step()                       # BNE
    model.disconnect()
    assert not machine.observers.active and model.executed == 1
    runner.run()
    assert model.executed == 1


def test_a_program_without_conditional_branches_adds_no_hook(build):
    machine = Machine(build(".global _start\n_start: MOV R0, #1\n        B next\n"
                            "next:   SVC #10\n"))
    model = BHTModel()
    model.connect(machine)
    assert model.machine is machine and not machine.observers.active
    Runner(machine).run()
    assert model.executed == 0 and not model.update()


def test_connected_without_a_program_it_observes_the_next_one(build):
    model = BHTModel()
    model.connect(None)
    assert model.connected and model.machine is None and model.next_branch() is None
    machine = Machine(build(LOOP.format(count=3)))
    model.observe(machine)
    Runner(machine).run()
    assert model.executed == 3


@pytest.mark.parametrize("direct", [True, False])
def test_watched_instructions_get_the_flags_they_find(build, monkeypatch, direct):
    """Observers.watch_code with flags: N, Z, C and V before the instruction runs, from the
    emulator of the moment (Reset makes a new one); also through the binding's own
    reg_read when ctypes cannot call Unicorn directly."""
    if not direct:
        monkeypatch.setattr(observers, "_REG_READ", None)
    machine = Machine(build(FLAGS))
    seen = []
    machine.observers.watch_code("tool", [0x4, 0xC, 0x18], lambda *args: seen.append(args),
                                 flags=True)
    runner = Runner(machine)
    runner.run()
    # Z after MOVS #0; N after 0 - 1 (a borrow: C clear); C and Z after -1 + 1.
    assert seen == [(0x4, 0b0100), (0xC, 0b1000), (0x18, 0b0110)]
    runner.reset()
    runner.step()
    runner.step()
    assert seen[-1] == (0x4, 0b0100) == (0x4, machine.cpsr >> 28)


# Speed ---------------------------------------------------------------------------------

@pytest.mark.serial
def test_ten_million_instructions_with_the_bht_simulator(build):
    """Connected, the simulator hooks the BNE of the loop, which runs 2,000,000 times: a
    Python call each, a few seconds in all.

    The time measured is the processor time of this process: on a machine
    busy with other test runs the clock time of this run can reach 12 s while
    its processor time stays near 5 s.
    """
    machine = Machine(build(BENCHMARK.read_text()))
    model = BHTModel()
    model.connect(machine)
    start, clock = time.process_time(), time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed, clock = time.process_time() - start, time.perf_counter() - clock
    assert machine.console.text.startswith("0xa9596240\n")
    assert model.executed == 2_000_000
    assert totals(model) == (2_000_000 - 2, 2)
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s of the processor ({clock:.3f} s)"
