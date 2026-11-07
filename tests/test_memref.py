# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Memory Reference Visualization's model: which unit counts what, its places and colours,
what survives Assemble and Reset, and its speed."""

import time
from collections import Counter, defaultdict

import pytest
from conftest import PROGRAMS
from test_observers import per_address

from ares.gui.tools.cache import CacheModel
from ares.gui.tools.memref import (COLOURS, COUNTS, ColourScale, VisualizationModel, accesses,
                                   bands, opposite, places, stack_page)
from ares.machine import Machine, StopReason
from ares.runner import Runner, State

WORDS = """\
        .data
values: .word   1, 2, 3, 4
        .global _start
        .text
_start: LDR     R1, =values
        LDR     R0, [R1]
        STR     R0, [R1, #8]
        LDRB    R2, [R1, #13]
        PUSH    {R0, R1}
        SVC     #10
"""
# The words at 0, the literal pool's word (values' address) after SVC, then values.
CODE_WORDS = 6
LOOP = """\
        .data
total:  .word   0
        .global _start
        .text
_start: LDR     R4, =total
        MOV     R0, #3
loop:   LDR     R1, [R4]
        ADD     R1, R1, R0
        STR     R1, [R4]
        SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
"""
NO_DATA = """\
        .global _start
        .text
_start: MOV     R0, #1
        SVC     #10
"""
STACK = """\
        .global _start
        .text
_start: LDR     SP, =0x40000000
        PUSH    {R0}
        LDR     SP, =0x1000
        SVC     #10
"""
# Accesses of 8 bytes: each reads or writes two words.
DOUBLES = """\
        .data
values: .word   1, 2, 3, 4, 5, 6
        .global _start
        .text
_start: LDR     R1, =values
        VLDR    D0, [R1]            @ values[0] and [1]
        VSTR    D0, [R1, #8]        @ values[2] and [3]
        VLDM    R1, {D1-D2}         @ values[0] to [3]
        VLD1.32 {D3}, [R1]          @ values[0] and [1]
        SVC     #10
"""
# The accesses format() puts in before SVC #10 reach values' words 0 to 3 through R1.
ACCESSES = """\
        .data
values: .word   1, 2, 3, 4
        .global _start
        .text
_start: LDR     R1, =values
{}        SVC     #10
"""
# Code that ends off a word: the section after it starts off a word too.
ODD_CODE = """\
        .section .boot, "ax"
        .global _start
_start: .byte   1
        .section .table, "a"
table:  .byte   2, 3, 4
"""


def make(build, source=WORDS):
    machine = Machine(build(source))
    return machine, Runner(machine)


def connected(machine, **settings):
    model = VisualizationModel()
    model.configure(**settings)
    model.connect(machine)
    return model


def shown(model):
    """{unit: count} of the units with a count."""
    model.update()
    return {unit: count for unit, count in enumerate(model.counts) if count}


def cached_words(cache):
    """The addresses of the words the Data Cache Simulator counted, from its log."""
    cache.update()
    return [int(entry.split("address ")[1][:10], 16) for entry in cache.log]


# What counts, in which unit ----------------------------------------------------------

def test_reads_and_writes_count_in_the_unit_of_their_address(build):
    machine, runner = make(build)
    values = machine.program.label_address("values")
    model = connected(machine, base=values)
    assert runner.run() is State.FINISHED
    # values[0] read, values[2] written, a byte of values[3] read; the code and the
    # stack are not shown.
    assert shown(model) == {0: 1, 2: 1, 3: 1}


def test_instructions_executed_count_as_reads_of_their_words(build):
    machine, runner = make(build)
    model = connected(machine, base=0)
    runner.run()
    model.update()
    counts = model.counts
    # Six instructions, the literal pool's word (LDR R1, =values) and then values.
    assert counts[:CODE_WORDS + 5] == [1] * CODE_WORDS + [1] + [1, 0, 1, 1]
    assert sum(counts) == CODE_WORDS + 4


def test_words_per_unit(build):
    machine, runner = make(build)
    model = connected(machine, base=0, words_per_unit=2)
    runner.run()
    assert model.unit_of(8) == model.unit_of(15) == 1 and model.unit_of(16) == 2
    assert shown(model) == {0: 2, 1: 2, 2: 2, 3: 2, 4: 1, 5: 1}


def test_the_display_ends_after_its_last_unit(build):
    """64 x 64 pixels of 32 x 32 pixel units: 4 units of one word, from PUSH on."""
    machine, runner = make(build)
    values = machine.program.label_address("values")
    model = connected(machine, base=values - 12, unit_width=32, unit_height=32, width=64,
                      height=64)
    assert (model.columns, model.rows, len(model.counts)) == (2, 2, 4)
    assert model.end == values + 3
    assert model.unit_of(values + 4) is None and model.unit_of(values - 16) is None
    runner.run()
    # PUSH and SVC executed, the pool's word and values[0] read; values[2] is not shown.
    assert shown(model) == {0: 1, 1: 1, 2: 1, 3: 1}


def test_an_access_of_two_words_counts_in_both(build):
    """VLDR D0, VSTR D0, VLDM of D registers and NEON loads read or write 8 bytes at once:
    each of the two words counts, as two word accesses would."""
    machine, runner = make(build, DOUBLES)
    values = machine.program.label_address("values")
    model = connected(machine, base=values)
    runner.run()
    assert shown(model) == {0: 3, 1: 3, 2: 2, 3: 2}
    # Two words per unit: both words of each access in the same unit.
    machine, runner = make(build, DOUBLES)
    model = connected(machine, base=values, words_per_unit=2)
    runner.run()
    assert shown(model) == {0: 6, 1: 4}
    # The display ends after the first word of values: the second word is not shown.
    machine, runner = make(build, DOUBLES)
    model = connected(machine, base=values - 12, unit_width=32, unit_height=32, width=64,
                      height=64)
    runner.run()
    assert shown(model) == {0: 1, 1: 1, 2: 1, 3: 3}   # VLD1, SVC, the pool's word, values[0]


@pytest.mark.parametrize("body, counts", [
    ("        LDR     R0, [R1, #2]\n", {0: 1, 1: 1}),
    ("        STR     R0, [R1, #7]\n", {1: 1, 2: 1}),
    ("        LDRH    R0, [R1, #11]\n", {2: 1, 3: 1}),
    ("        LDRH    R0, [R1, #2]\n        STRB    R0, [R1, #3]\n", {0: 2}),
    ("        ADD     R2, R1, #2\n        VLD1.8  {D3}, [R2]\n", {0: 1, 1: 1, 2: 1}),
    ("        LDREX   R2, [R1]\n        STREX   R3, R2, [R1]\n", {0: 3}),
    ("        STREX   R3, R2, [R1]\n", {}),           # no LDREX before: it fails
])
def test_each_word_an_access_covers_counts_in_its_unit(build, body, counts):
    """An unaligned LDR, STR or LDRH that reaches into the next word counts in the units of
    both words, an unaligned VLD1 of 8 bytes in those of its three words, a halfword or a byte
    inside its word once. LDREX counts one, STREX two when it stores (the processor ARES
    simulates reads the word before it writes it). The Data Cache Simulator counts the same
    words in the same run."""
    machine, runner = make(build, ACCESSES.format(body))
    values = machine.program.label_address("values")
    model = connected(machine, base=values)
    cache = CacheModel()
    cache.set_logging(True)
    cache.connect(machine)
    assert runner.run() is State.FINISHED
    assert shown(model) == counts
    words = [(address - values) // 4 for address in cached_words(cache) if address >= values]
    assert Counter(words) == counts


def test_an_access_across_words_at_the_end_of_a_unit_and_of_the_display(build):
    """Two words per unit: LDR R0, [R1, #6] reads values[1] and [2], in units 0 and 1. A word
    after the display's end, or after the end of the address space, does not count."""
    machine, runner = make(build, ACCESSES.format("        LDR     R0, [R1, #6]\n"))
    values = machine.program.label_address("values")
    model = connected(machine, base=values, words_per_unit=2)
    runner.run()
    assert shown(model) == {0: 1, 1: 1}
    # The display ends after values[0]: LDR R0, [R1, #2] also reads values[1], not shown.
    machine, runner = make(build, ACCESSES.format("        LDR     R0, [R1, #2]\n"))
    values = machine.program.label_address("values")
    model = connected(machine, base=values - 12, unit_width=32, unit_height=32, width=64,
                      height=64)
    runner.run()
    assert shown(model) == {0: 1, 1: 1, 2: 1, 3: 1}   # LDR, SVC, the pool's word, values[0]
    # A word read at 0xFFFFFFFE runs on at address 0, after the display's end.
    machine, runner = make(build, ACCESSES.format("        MVN     R2, #1\n"
                                                  "        LDR     R0, [R2]\n"))
    model = connected(machine, base=0xFFFFFE00)
    assert runner.run() is State.FINISHED
    assert shown(model) == {127: 1}


def test_the_stack_at_the_top_of_the_address_space(build):
    """SP's start value 0: the first push stores at the end of the on-chip memory, where
    the address space and the display end."""
    machine, runner = make(build)
    model = connected(machine, base=0xFFFFFE00)
    assert model.end == 0xFFFFFFFF
    runner.run()
    assert shown(model) == {126: 1, 127: 1}                 # PUSH {R0, R1}


def test_loops_count_every_pass(build):
    machine, runner = make(build, LOOP)
    total = machine.program.label_address("total")
    loop = machine.program.label_address("loop")
    model = connected(machine, base=0)
    runner.run()
    counts = shown(model)
    assert [counts[loop // 4 + k] for k in range(5)] == [3] * 5
    assert counts[total // 4] == 2 * 3                      # read and written 3 times


def test_instructions_count_once_they_completed(build):
    """A breakpoint inside a block stops before its instruction, which counts when it runs:
    the counts of the code are those of the instructions completed."""
    machine, runner = make(build, LOOP)
    loop = machine.program.label_address("loop")
    code = machine.program.label_address("total") // 4 - 1     # the pool's word follows
    blocks = machine.observers.count_blocks("reference")
    model = connected(machine, base=0)
    runner.set_breakpoint(loop + 8)                             # STR R1, [R4]
    runner.step()
    stops = 0
    while runner.run() is not State.FINISHED:
        stops += 1
        assert machine.pc == loop + 8
        model.update()
        executed = per_address(blocks.runs)
        assert model.counts[:code] == [executed[4 * unit] for unit in range(code)]
        assert model.counts[(loop + 8) // 4] == model.counts[loop // 4] - 1 == stops - 1
    model.update()
    assert stops == 3 and model.counts[loop // 4:loop // 4 + 5] == [3] * 5


def test_instructions_are_counted_while_the_display_shows_code(build):
    """Only then is the shared block hook there: data, heap and stack cost no block hook."""
    machine, runner = make(build)
    values = machine.program.label_address("values")
    model = connected(machine, base=values)
    assert machine.observers.active and machine.observers.blocks is None
    model.configure(base=0xFFFFFE00)
    assert machine.observers.blocks is None
    model.configure(base=values - 4)        # the end of the code's section: its literal pool
    assert machine.observers.blocks is not None
    runner.run()
    assert shown(model) == {0: 1, 1: 1, 3: 1, 4: 1}       # the pool's word read, and values
    model.disconnect()
    assert not machine.observers.active


def test_the_observers_count_accesses_per_unit(build):
    machine, runner = make(build)
    values = machine.program.label_address("values")
    counts = defaultdict(int)
    machine.observers.count_accesses("tool", counts, values, values + 15, shift=3)
    runner.run()
    assert counts == {0: 1, 1: 2}           # values[0] read; values[2] written, values[3] read
    machine.observers.forget("tool")
    assert not machine.observers.active


def test_nothing_is_counted_while_disconnected(build):
    machine, runner = make(build)
    model = VisualizationModel()
    model.observe(machine)                  # not connected: the program is not observed
    assert model.machine is None and not machine.observers.active
    runner.step()
    model.connect(machine)
    assert machine.observers.active
    runner.step()
    model.disconnect()
    assert not machine.observers.active
    # The second instruction only: LDR R0, [R1] executed, and values[0] read.
    assert shown(model) == {1: 1, CODE_WORDS + 1: 1}
    runner.run()
    assert shown(model) == {1: 1, CODE_WORDS + 1: 1}


# Settings, Reset and what survives -----------------------------------------------------

def test_settings_start_again_and_move_the_observed_memory(build):
    machine, runner = make(build)
    values = machine.program.label_address("values")
    model = connected(machine, base=0)
    runner.step()
    model.update()
    assert model.counts[0] == 1 and model.take_changes() is None
    model.configure(base=values)
    assert model.counts == [0] * 256 and model.take_changes() is None
    runner.run()
    assert shown(model) == {0: 1, 2: 1, 3: 1}               # only values now
    model.configure(words_per_unit=4)
    assert not any(model.counts)
    with pytest.raises(ValueError):
        model.configure(words_per_unit=3)
    with pytest.raises(ValueError):
        model.configure(base=values + 2)


def test_the_changes_to_draw(build):
    machine, runner = make(build)
    values = machine.program.label_address("values")
    model = connected(machine, base=values)
    assert model.take_changes() is None                     # a new display: everything
    assert model.take_changes() == set() and not model.update()
    runner.run()
    assert model.update()
    assert model.take_changes() == {0, 2, 3}
    assert model.take_changes() == set() and not model.update()
    model.reset()
    assert model.update() and model.take_changes() is None


def test_reset_starts_again_from_zero(build):
    machine, runner = make(build, LOOP)
    model = connected(machine, base=0)
    runner.step()
    runner.step()
    model.reset()                           # also what ran since the last update
    assert not any(model.counts)
    runner.run()
    loop = machine.program.label_address("loop")
    counts = shown(model)
    assert counts.get(0) is None and counts[loop // 4] == 3


def test_counts_go_on_across_reset_backstep_and_assemble(build):
    machine, runner = make(build)
    model = connected(machine, base=0)
    for _ in range(3):
        runner.step()
    runner.backstep()                       # undone, but it ran
    assert shown(model) == {0: 1, 1: 1, 2: 1, CODE_WORDS: 1, CODE_WORDS + 1: 1, CODE_WORDS + 3: 1}
    runner.reset()                          # Reset, F12
    runner.run()
    assert shown(model)[2] == 2
    other, other_runner = make(build)       # Assemble: the window passes the new machine
    model.observe(other)
    assert not machine.observers.active and model.machine is other
    other_runner.run()
    assert shown(model)[2] == 3
    model.observe(None)                     # the program's file closed: still connected
    assert model.connected and not other.observers.active and shown(model)[2] == 3


def test_connected_without_a_program_it_counts_the_next_one(build):
    model = VisualizationModel()
    model.connect(None)
    assert model.connected and model.machine is None
    machine, runner = make(build)
    model.observe(machine)
    runner.run()
    assert shown(model)[0] == 1


def test_it_shares_the_block_counting_with_other_tools(build):
    machine, runner = make(build, LOOP)
    blocks = machine.observers.count_blocks("counter")
    model = connected(machine, base=0)
    assert machine.observers.blocks is blocks
    runner.run()
    model.disconnect()
    assert machine.observers.blocks is blocks       # the other tool still counts
    machine.observers.forget("counter")
    assert not machine.observers.active


# Places --------------------------------------------------------------------------------

def test_the_places_of_a_program(build):
    machine, _ = make(build)
    values = machine.program.label_address("values")
    assert places(machine) == [(".data", values), ("heap", values + 16),
                               ("current SP", 0xFFFFFE00), (".text", 0)]
    assert machine.heap_start == values + 16


def test_without_data_the_data_starts_at_the_end_of_the_program(build):
    machine, _ = make(build, NO_DATA)
    assert dict(places(machine))[".data"] == dict(places(machine))["heap"] == 8


def test_the_places_start_on_a_word(build):
    """Code that ends off a word puts the data off a word: the display starts on the word
    that holds the data's first byte."""
    machine, _ = make(build, ODD_CODE)
    table = machine.program.label_address("table")
    assert table % 4 == 1
    assert places(machine) == [(".data", table - 1), ("heap", table + 3),
                               ("current SP", 0xFFFFFE00), (".text", 0)]
    model = VisualizationModel()
    for _, address in places(machine):
        model.configure(base=address)


def test_without_a_program(build):
    """The places of the program have no address; current SP is SP's start value's."""
    assert places(None) == [(".data", None), ("heap", None), ("current SP", 0xFFFFFE00),
                            (".text", None)]


def test_the_current_sp_place_is_the_data_segments(build):
    machine, runner = make(build, STACK)
    assert dict(places(machine))["current SP"] == 0xFFFFFE00     # SP = 0: the first push
    runner.step()                                               # SP = 0x40000000
    assert dict(places(machine))["current SP"] == 0x3FFFFE00
    runner.step()                                               # PUSH: SP = 0x3FFFFFFC
    assert dict(places(machine))["current SP"] == 0x3FFFFE00
    runner.step()                                               # SP = 0x1000
    assert dict(places(machine))["current SP"] == 0x1000
    assert stack_page(0x1234) == 0x1220 and stack_page(0xFFFFFFF0) == 0xFFFFFE00


# Colours -------------------------------------------------------------------------------

def test_the_colours_of_the_counts():
    scale = ColourScale()
    assert [scale.colour(count) for count in (0, 1, 2, 3, 4, 5, 9, 10, 1000000)] == [
        "#000000", "#0000FF", "#00FF00", "#FFFF00", "#FFFF00", "#FFC800", "#FFC800",
        "#FF0000", "#FF0000"]
    assert [scale.last(count) for count in (0, 1, 3, 4, 5, 7, 10, 500)] == [
        0, 1, 4, 4, 9, 9, None, None]
    assert [scale.level(count) for count in (0, 2, 4, 9, 10, 99)] == [0, 2, 3, 4, 5, 5]
    assert scale.colours == list(COLOURS) and COLOURS[0][0] == 0


def test_a_colour_set_for_a_count_applies_up_to_the_next_colour():
    scale = ColourScale()
    scale.set(4, "#123456")                 # inside 3 to 4: 4 gets a colour of its own
    assert [scale.colour(count) for count in (3, 4, 5)] == ["#FFFF00", "#123456", "#FFC800"]
    assert scale.last(3) == 3 and scale.last(4) == 4
    scale.set(1, "#ABCDEF")                 # a count that starts a colour: replaced
    assert scale.colour(1) == "#ABCDEF" and len(scale.colours) == len(COLOURS) + 1
    scale.set(20, "#000080")
    assert scale.last(10) == 19 and scale.last(20) is None and scale.colour(25) == "#000080"
    assert [scale.level(count) for count in (0, 3, 4, 5, 10, 20)] == [0, 3, 4, 5, 6, 7]


def test_the_counts_the_slider_offers():
    assert COUNTS[:11] == tuple(range(11)) and COUNTS[-1] == 1_000_000
    assert COUNTS[11:] == (20, 30, 40, 50, 100, 200, 300, 400, 500, 1000, 2000, 3000, 4000,
                           5000, 10_000, 50_000, 100_000, 500_000, 1_000_000)
    assert list(COUNTS) == sorted(set(COUNTS))
    assert all(start in COUNTS for start, _ in COLOURS)


def test_the_words_for_counts_and_colours():
    assert accesses(0, 0) == "0 accesses" and accesses(1, 1) == "1 access"
    assert accesses(3, 4) == "3 to 4 accesses" and accesses(10, None) == "10 or more accesses"
    assert accesses(1000, None) == "1,000 or more accesses"
    assert opposite("#000000") == "#FFFFFF" and opposite("#0000FF") == "#FFFF00"
    assert bands({8, 2, 1, 3, 5}) == [[1, 3], [5, 5], [8, 8]] and bands(set()) == []


# Speed ---------------------------------------------------------------------------------

@pytest.mark.serial
def test_ten_million_instructions_connected(build):
    """Connected at the start of the program, the tool counts every instruction of
    loop10m.s and every access to its total: under 10 s (about 3 s on an idle computer)."""
    machine = Machine(build((PROGRAMS / "loop10m.s").read_text()))
    model = VisualizationModel()            # base 0: the code and the data of loop10m.s
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    total = machine.program.label_address("total")
    loop = machine.program.label_address("loop")
    assert model.counts[total // 4] == 2 * 2_000_000 + 2
    assert model.counts[loop // 4:loop // 4 + 5] == [2_000_000] * 5
    assert elapsed < 10.0, f"{elapsed:.3f} s"
