# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""What connected tools observe: basic blocks counted, memory accesses, watched instructions.

Counting per basic block must give exactly the counts of a counter that sees
every instruction, also for runs that stop inside a block.
"""

import threading
from collections import Counter

import pytest
from conftest import PROGRAMS
from unicorn import UC_HOOK_CODE, UC_MEM_READ, UC_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC

from ares.machine import CHUNK, Machine, StopReason
from ares.runner import Runner, State

PROGRAMS_WITH_OUTPUT = sorted(p for p in PROGRAMS.glob("*.s")
                              if p.with_suffix(".out").is_file() and p.name != "loop10m.s")

LOOP = """\
        .global _start
_start: MOV     R0, #0
        MOV     R1, #0
loop:   ADD     R0, R0, #1
        ADD     R1, R1, R0
        CMP     R0, #{count}
        BNE     loop
        SVC     #10
"""
FOREVER = """\
        .global _start
_start: ADD     R0, R0, #1
        ADD     R1, R1, #2
        ADD     R2, R2, #3
        B       _start
"""
READ_INT = """\
        .global _start
_start: MOV     R4, #1
        SVC     #5
        ADD     R0, R0, R4
        SVC     #1
        SVC     #10
"""
HINTS = """\
        .global _start
_start: MOV     R0, #0
loop:   ADD     R0, R0, #1
        WFE
        YIELD
        CMP     R0, #3
        BNE     loop
        SVC     #10
"""
DROPS_OFF = ".global _start\n_start: MOV R0, #1\n        ADD R0, R0, #2\n        ADD R0, R0, #3\n"
SELF_BRANCH = ".global _start\n_start: MOV R0, #1\n        ADD R0, R0, #2\n        B .\n"


class Reference:
    """Counts every completed instruction with a code hook on every instruction.

    The rule is the block counter's: an instruction the run stopped at did
    not complete (a breakpoint, Pause, the end of a step or a chunk, a system
    call that waits, a runtime error, which also counts for the failing
    instruction whatever PC is); a WFE or YIELD stepped over counts once.
    """

    def __init__(self, machine):
        self.machine = machine
        self.counts = Counter()
        reset, skip = machine.reset, machine._skip_wait_hint

        def reset_and_attach():
            reset()
            self.attach()

        def skip_counted(record):
            self.counts[machine.pc] += 1
            skip(record)
        machine.reset = reset_and_attach
        machine._skip_wait_hint = skip_counted
        self.attach()

    def attach(self):
        """Hook the machine's emulator (a Reset makes a new one)."""
        machine, uc = self.machine, self.machine.uc
        self.last = None

        def reached(uc, address, size, data):
            self.last = address
            self.counts[address] += 1
        uc.hook_add(UC_HOOK_CODE, reached)
        uc.ctl_flush_tb()
        start = uc.emu_start

        def emu_start(begin, until, timeout=0, count=0):
            try:
                start(begin, until, timeout, count)
            finally:
                where = (machine.error_address if machine.stop_reason is StopReason.ERROR
                         else uc.reg_read(UC_ARM_REG_PC))
                if self.last is not None and where == self.last:
                    self.counts[self.last] -= 1
                self.last = None
        uc.emu_start = emu_start


def per_address(runs):
    """Completed runs of each instruction, from BlockCounts.runs."""
    counts = Counter()
    for (address, size), n in runs.items():
        for at in range(address, address + size, 4):
            counts[at] += n
    return +counts


def counted(build, source, input_text=None, record=False):
    """(machine, block counts, reference, runner) for source, counting from the start."""
    machine = Machine(build(source))
    if input_text is not None:
        machine.console.feed(input_text)
        machine.console.close_input()
    blocks = machine.observers.count_blocks("test")
    return machine, blocks, Reference(machine), Runner(machine, record_while_running=record)


def assert_same(blocks, reference):
    assert per_address(blocks.runs) == +reference.counts
    assert blocks.instructions() == sum(reference.counts.values())


# Whole programs -------------------------------------------------------------

@pytest.mark.parametrize("source", PROGRAMS_WITH_OUTPUT, ids=lambda p: p.name)
def test_whole_programs_count_alike(build, source):
    typed = source.with_suffix(".in")
    machine, blocks, reference, runner = counted(
        build, source.read_text(), typed.read_text() if typed.is_file() else "")
    assert runner.run() is State.FINISHED and machine.error is None
    assert blocks.instructions() > 0
    assert_same(blocks, reference)


def test_runs_longer_than_a_chunk(build):
    """Chunks of CHUNK instructions end inside the loop's block again and again."""
    machine, blocks, reference, runner = counted(build, LOOP.format(count=6144))
    assert runner.run() is State.FINISHED
    assert blocks.instructions() == 2 + 4 * 6144 + 1 > 2 * CHUNK
    assert_same(blocks, reference)


@pytest.mark.parametrize("source, reason", [(DROPS_OFF, StopReason.DROPPED_OFF),
                                            (SELF_BRANCH, StopReason.SELF_BRANCH)])
def test_programs_that_end_without_exit(build, source, reason):
    machine, blocks, reference, runner = counted(build, source)
    runner.run()
    assert machine.stop_reason is reason
    assert blocks.instructions() == (3 if reason is StopReason.DROPPED_OFF else 2)  # B . never runs
    assert_same(blocks, reference)


# Runs that stop inside a block ---------------------------------------------------

def test_breakpoint_inside_a_block(build):
    machine, blocks, reference, runner = counted(build, LOOP.format(count=5))
    second = machine.program.label_address("loop") + 4            # ADD R1, R1, R0
    runner.set_breakpoint(second)
    for iteration in range(1, 6):
        assert runner.run() is State.PAUSED and machine.pc == second
        assert blocks.instructions() == 2 + 4 * (iteration - 1) + 1
        assert_same(blocks, reference)
    assert runner.run() is State.FINISHED
    assert_same(blocks, reference)


def test_pause_between_slices(build):
    machine, blocks, reference, runner = counted(build, FOREVER)
    for _ in range(3):
        runner.go()
        runner.run_slice()
        runner.run_slice()
        runner.pause()
        assert runner.run_slice() is State.PAUSED
        assert_same(blocks, reference)


def test_pause_from_another_thread(build):
    machine, blocks, reference, runner = counted(build, FOREVER)
    timer = threading.Timer(0.1, runner.pause)
    timer.start()
    try:
        assert runner.run(time_limit=10) is State.PAUSED
    finally:
        timer.cancel()
    assert blocks.instructions() > CHUNK
    assert_same(blocks, reference)


def test_a_waiting_service_counts_once_when_it_completes(build):
    machine, blocks, reference, runner = counted(build, READ_INT)
    assert runner.run() is State.WAITING
    assert blocks.instructions() == 1                             # the SVC #5 waits
    assert_same(blocks, reference)
    machine.console.feed("41\n")
    assert runner.run() is State.FINISHED and machine.console.text.startswith("42")
    assert blocks.instructions() == 5
    assert_same(blocks, reference)


def test_a_breakpoint_on_a_waiting_service(build):
    machine, blocks, reference, runner = counted(build, READ_INT)
    service = machine.program.entry + 4
    runner.set_breakpoint(service)
    assert runner.run() is State.PAUSED and machine.pc == service
    assert_same(blocks, reference)
    assert runner.run() is State.WAITING
    assert_same(blocks, reference)
    machine.console.feed("1\n")
    assert runner.run() is State.FINISHED
    assert blocks.instructions() == 5
    assert_same(blocks, reference)


@pytest.mark.parametrize("failing", [
    "        MOV     R1, #0x50000000\n        LDR     R2, [R1]\n",  # memory out of range
    "        .word   0xE6000010\n",                                   # undefined instruction
    "        SVC     #99\n",                                          # unknown service
])
def test_a_runtime_error_inside_a_block(build, failing):
    source = (".global _start\n_start: MOV R0, #1\n        ADD R0, R0, #2\n" + failing
              + "        ADD R0, R0, #3\n        SVC #10\n")
    machine, blocks, reference, runner = counted(build, source)
    assert runner.run() is State.FINISHED and machine.stop_reason is StopReason.ERROR
    assert blocks.instructions() == failing.count("\n") + 1      # all before the failing one
    assert machine.error_address not in per_address(blocks.runs)
    assert_same(blocks, reference)


def test_step_after_step_and_backstep(build):
    machine, blocks, reference, runner = counted(build, LOOP.format(count=3))
    for steps in range(1, 8):
        runner.step()
        assert blocks.instructions() == steps
        assert_same(blocks, reference)
    runner.backstep()
    runner.backstep()
    assert blocks.instructions() == 7                             # undone, but they ran
    for _ in range(3):
        runner.step()
        assert_same(blocks, reference)
    assert runner.run() is State.FINISHED
    assert_same(blocks, reference)


def test_reset_keeps_counting_on_the_new_emulator(build):
    machine, blocks, reference, runner = counted(build, LOOP.format(count=4))
    runner.set_breakpoint(machine.program.label_address("loop") + 8)
    runner.run()
    runner.reset()
    assert machine.observers.blocks is blocks
    runner.set_breakpoint(machine.program.label_address("loop") + 8, False)
    assert runner.run() is State.FINISHED
    assert blocks.instructions() == 2 + 2 + (2 + 4 * 4 + 1)
    assert_same(blocks, reference)


@pytest.mark.parametrize("how", ["go", "step", "breakpoint"])
def test_wfe_and_yield_stepped_over_count_once(build, how):
    machine, blocks, reference, runner = counted(build, HINTS)
    if how == "step":
        while runner.step() is not State.FINISHED:
            assert_same(blocks, reference)
    else:
        if how == "breakpoint":
            runner.set_breakpoint(machine.program.label_address("loop") + 4)     # WFE
        while runner.run() is not State.FINISHED:
            assert_same(blocks, reference)
    assert blocks.instructions() == 1 + 5 * 3 + 1
    assert_same(blocks, reference)


@pytest.mark.parametrize("slow", [False, True])
def test_recorded_and_slow_runs(build, slow):
    """Backstep While Running stops runs before an instruction at the slice's end; a slow
    run steps one instruction at a time."""
    machine, blocks, reference, runner = counted(build, LOOP.format(count=300),
                                                 record=not slow)
    runner.go(slow=slow)
    while runner.state is State.RUNNING:
        runner.run_slice()
    assert machine.stop_reason is StopReason.EXIT
    assert blocks.instructions() == 2 + 4 * 300 + 1
    assert_same(blocks, reference)


def test_counting_connected_later_counts_from_then(build):
    """Code translated before the block hook was added is dropped, so nothing is missed."""
    machine = Machine(build(LOOP.format(count=50)))
    reference = Reference(machine)
    runner = Runner(machine)
    for _ in range(9):
        runner.step()                   # the loop is translated without the block hook
    before = Counter(reference.counts)
    blocks = machine.observers.count_blocks("test")
    assert runner.run() is State.FINISHED
    assert per_address(blocks.runs) == +(reference.counts - before)


# The observers themselves ---------------------------------------------------------

def hooks(machine):
    return len(machine.uc._callbacks)


def test_nothing_is_installed_while_no_tool_observes(build):
    machine = Machine(build(LOOP.format(count=3)))
    alone = hooks(machine)
    assert not machine.observers.active and machine.observers.blocks is None
    first = machine.observers.count_blocks("first")
    second = machine.observers.count_blocks("second")
    assert first is second and hooks(machine) == alone + 1     # one shared hook
    machine.observers.forget("first")
    assert machine.observers.blocks is first and hooks(machine) == alone + 1
    machine.observers.forget("second")
    assert machine.observers.blocks is None and hooks(machine) == alone
    assert not machine.observers.active
    machine.reset()
    assert hooks(machine) == alone


def test_each_tool_keeps_its_own_baseline(build):
    machine = Machine(build(LOOP.format(count=10)))
    runner = Runner(machine)
    first = machine.observers.count_blocks("first")
    for _ in range(5):
        runner.step()
    seen = dict(first.runs)
    second = machine.observers.count_blocks("second")
    assert second is first
    runner.run()
    new = Counter(first.runs)
    new.subtract(seen)
    assert first.instructions() == 2 + 4 * 10 + 1
    assert sum(count * size // 4 for (_, size), count in new.items()) == 2 + 4 * 10 + 1 - 5


MEMORY = """\
        .data
value:  .word   5
other:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
        LDR     R0, [R1]
        ADD     R0, R0, #1
        STR     R0, [R1, #4]
        STRB    R0, [R1]
        SVC     #10
"""


def test_memory_accesses_are_reported(build):
    machine = Machine(build(MEMORY))
    value = machine.program.label_address("value")
    seen = []
    machine.observers.watch_memory("tool", lambda *access: seen.append(access))
    Runner(machine).run()
    literal = [access for access in seen if access[1] != value and access[1] != value + 4]
    assert len(literal) == 1 and literal[0][0] == UC_MEM_READ           # LDR R1, =value
    assert [access for access in seen if access not in literal] == [
        (UC_MEM_READ, value, 4, 0), (UC_MEM_WRITE, value + 4, 4, 6),
        (UC_MEM_WRITE, value, 1, 6)]


def test_memory_accesses_in_a_range_and_after_reset(build):
    machine = Machine(build(MEMORY))
    value = machine.program.label_address("value")
    seen = []
    machine.observers.watch_memory("tool", lambda *access: seen.append(access), reads=False,
                                   begin=value + 4, end=value + 7)
    runner = Runner(machine)
    runner.run()
    assert seen == [(UC_MEM_WRITE, value + 4, 4, 6)]
    runner.reset()
    runner.run()
    assert seen == [(UC_MEM_WRITE, value + 4, 4, 6)] * 2
    machine.observers.forget("tool")
    runner.reset()
    runner.run()
    assert len(seen) == 2 and not machine.observers.active


def test_memory_accesses_with_unicorns_own_arguments(build):
    """raw: the callback is Unicorn's hook itself, one Python call per access."""
    machine = Machine(build(MEMORY))
    value = machine.program.label_address("value")
    seen = []
    machine.observers.watch_memory("tool", lambda *arguments: seen.append(arguments[1:5]),
                                   begin=value, end=value + 7, raw=True)
    Runner(machine).run()
    assert seen == [(UC_MEM_READ, value, 4, 0), (UC_MEM_WRITE, value + 4, 4, 6),
                    (UC_MEM_WRITE, value, 1, 6)]


def test_watched_instructions_are_reported_once_per_run(build):
    """Also when a run stops at them: a breakpoint set before or after the watch, Step."""
    machine = Machine(build(LOOP.format(count=6)))
    reference = Reference(machine)
    runner = Runner(machine)
    add = machine.program.label_address("loop")
    compare = add + 8
    runner.set_breakpoint(add)
    seen = []
    machine.observers.watch_code("tool", [add, compare], seen.append)
    runner.set_breakpoint(compare)
    runner.step()
    runner.step()
    while runner.run() is not State.FINISHED:
        assert seen.count(add) == reference.counts[add]
        assert seen.count(compare) == reference.counts[compare]
    assert seen.count(add) == seen.count(compare) == 6
    machine.observers.forget("tool")
    assert not machine.observers.active


def test_watched_instructions_in_a_recorded_run(build):
    machine = Machine(build(LOOP.format(count=200)))
    runner = Runner(machine, record_while_running=True)
    seen = []
    machine.observers.watch_code("tool", [machine.program.label_address("loop")], seen.append)
    runner.go()
    while runner.state is State.RUNNING:
        runner.run_slice()
    assert len(seen) == 200


def test_a_recorded_run_that_ends_its_slice_at_a_watched_instruction(build):
    """The slice's end stops a recorded run before an instruction: a watched one there is
    reported when it runs, once."""
    machine = Machine(build(LOOP.format(count=20)))
    add = machine.program.label_address("loop")
    seen = []
    machine.observers.watch_code("tool", [add], seen.append)
    record, ends, resumed = machine._on_instruction, [], [False]

    def slice_ends_at_add(uc, address, size, data):
        if address == add and len(ends) < 5 and not resumed[0]:
            ends.append(address)
            resumed[0] = True           # the next run starts here and runs it
            uc.emu_stop()               # as the end of the slice does, before the instruction
            return
        resumed[0] = False
        record(uc, address, size, data)
    machine._on_instruction = slice_ends_at_add
    runner = Runner(machine, record_while_running=True)
    runner.go()
    while runner.state is State.RUNNING:
        runner.run_slice()
    assert len(ends) == 5 and machine.stop_reason is StopReason.EXIT
    assert seen.count(add) == 20


COUNT_IN_MEMORY = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
        MOV     R2, #0
loop:   LDR     R0, [R1]
        ADD     R0, R0, #1
        STR     R0, [R1]
        ADD     R2, R2, #1
        CMP     R2, #0x10000
        BNE     loop
        SVC     #10
"""


def test_watches_added_after_the_code_ran(build):
    """Code translated before a watch was added is dropped, so nothing is missed."""
    machine = Machine(build(COUNT_IN_MEMORY))
    assert machine.run_slice(0) is None             # a chunk: the loop is translated
    loop, value = machine.program.label_address("loop"), machine.program.label_address("value")
    stored = int.from_bytes(machine.read_memory(value, 4), "little")
    loaded = machine.pc in (loop + 4, loop + 8)     # the LDR of the next value has run
    added = machine.pc == loop + 8                  # and its ADD
    accesses, reached = [], []
    machine.observers.watch_memory("tool", lambda *access: accesses.append(access),
                                   begin=value, end=value + 3)
    machine.observers.watch_code("tool", [loop + 4], reached.append)
    assert Runner(machine).run() is State.FINISHED
    assert [access[3] for access in accesses if access[0] == UC_MEM_WRITE] == list(
        range(stored + 1, 0x10001))
    assert sum(access[0] == UC_MEM_READ for access in accesses) == 0x10000 - stored - loaded
    assert len(reached) == 0x10000 - stored - added


def test_the_value_of_a_doubleword_write(build):
    """Values are unsigned, also those of 8-byte writes."""
    machine = Machine(build(".data\nvalue: .word 0, 0\n.global _start\n.text\n"
                            "_start: LDR R1, =value\n        MOV R2, #0\n        MVN R3, #0\n"
                            "        VMOV D0, R2, R3\n        VSTR D0, [R1]\n        SVC #10\n"))
    seen = []
    machine.observers.watch_memory("tool", lambda *access: seen.append(access), reads=False)
    assert Runner(machine).run() is State.FINISHED
    assert seen == [(UC_MEM_WRITE, machine.program.label_address("value"), 8,
                     0xFFFFFFFF00000000)]


@pytest.mark.parametrize("watch", ["memory", "code"])
def test_an_error_in_a_tools_callback_stops_the_run(build, watch):
    """It comes out of the run, as an error in one of the machine's own hooks does."""
    machine = Machine(build(MEMORY))

    def broken(*args):
        raise ValueError("the tool failed")
    if watch == "memory":
        machine.observers.watch_memory("tool", broken)
    else:
        machine.observers.watch_code("tool", [machine.program.entry + 8], broken)
    with pytest.raises(ValueError, match="the tool failed"):
        Runner(machine).run()
    assert machine.stop_reason is None
