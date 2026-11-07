# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Digital Lab Sim's model: the board it gives the program while connected, what survives
Assemble and Reset, and its cost."""

import time

import pytest
from conftest import PROGRAMS
from test_benchmark import TOOL_SECONDS

from ares.devices import LEDS, SWITCHES
from ares.gui.tools.labsim import LabSimModel
from ares.machine import Machine, StopReason
from ares.runner import Runner, State

LIGHTS = """\
        .global _start
_start: LDR     R0, =0xFF200000
        LDR     R1, [R0, #0x40]         @ the switches ...
        STR     R1, [R0]                @ ... light their LEDs
        MOV     R2, #0x06
        STR     R2, [R0, #0x20]         @ HEX0: 1
        SVC     #10
"""


def make(build, source=LIGHTS):
    machine = Machine(build(source))
    return machine, Runner(machine)


def test_connected_the_program_reaches_the_board(build):
    machine, runner = make(build)
    model = LabSimModel()
    model.observe(machine)                  # not connected: the devices are not simulated
    assert machine.board is None
    model.board.flip(1)
    model.connect(machine)
    assert model.machine is machine and machine.board is model.board
    assert runner.run() is State.FINISHED
    assert model.board.leds == 0b10 and model.board.segments(0) == 0x06
    assert machine.warnings == []
    model.disconnect()
    assert machine.board is None and not model.connected
    assert model.board.leds == 0b10                     # the window still shows it


def test_disconnected_the_program_reads_0_and_is_warned(build):
    machine, runner = make(build)
    model = LabSimModel()
    model.board.flip(1)
    runner.run()
    assert model.board.leds == 0 and machine.reg(1) == 0
    assert len(machine.warnings) == 3                   # the switches, LEDs and HEX3-HEX0


def test_the_board_survives_reset_assemble_and_closing_the_file(build):
    machine, runner = make(build)
    model = LabSimModel()
    model.connect(machine)
    model.board.flip(4)
    runner.run()
    runner.reset()                                      # Reset, F12: the board keeps it all
    assert machine.board is model.board and model.board.leds == 0b10000
    other, other_runner = make(build, ".global _start\n_start: B .\n")
    model.observe(other)                                # assembled again
    assert machine.board is None and other.board is model.board
    assert model.board.leds == 0b10000 and model.board.switches == 0b10000
    assert other.peek_words(LEDS, 1) == [0b10000]
    model.observe(None)                                 # the program's file closed
    assert model.connected and other.board is None and model.board.leds == 0b10000


def test_connected_without_a_program_it_takes_the_next_one(build):
    model = LabSimModel()
    model.connect(None)
    assert model.connected and model.machine is None
    machine, runner = make(build)
    model.observe(machine)
    assert machine.board is model.board


def test_update_tells_when_the_board_changed(build):
    machine, runner = make(build)
    model = LabSimModel()
    model.connect(machine)
    assert not model.update()
    model.board.flip(0)
    assert model.update() and not model.update()
    runner.step()
    runner.step()                           # a read changes nothing
    assert not model.update()
    runner.step()                           # SW0 lights LEDR0
    assert model.update() and not model.update()


def test_reset_switches_the_board_off(build):
    machine, runner = make(build)
    model = LabSimModel()
    model.connect(machine)
    model.board.flip(0)
    model.board.press(2)
    runner.run()
    model.reset()
    board = model.board
    assert (board.leds, board.hex3_hex0, board.switches, board.keys, board.edges) == (0, 0, 0,
                                                                                       0, 0)
    assert model.connected and machine.board is board and model.update()


def test_a_connected_lab_sim_adds_no_hook(build):
    machine, runner = make(build)
    hooks = len(machine.uc._callbacks)
    model = LabSimModel()
    model.connect(machine)
    assert len(machine.uc._callbacks) == hooks and not machine.observers.active
    runner.reset()
    assert machine.peek_words(SWITCHES, 1) == [0]


@pytest.mark.serial
def test_ten_million_instructions_with_the_lab_sim_connected(build):
    """The benchmark touches no device: connected, the Lab Sim costs it nothing."""
    machine = Machine(build((PROGRAMS / "loop10m.s").read_text()))
    model = LabSimModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    assert machine.console.text.startswith("0xa9596240\n")
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s"


@pytest.mark.serial
def test_a_program_that_counts_on_the_leds_runs_quickly(build):
    """Each access to the board calls Python once: 100,000 of them take about half a
    second (twice as long as the same accesses not simulated)."""
    machine = Machine(build("""\
        .global _start
_start: LDR     R0, =0xFF200000
        LDR     R1, =50000
loop:   STR     R1, [R0]                @ the LEDs show the count
        LDR     R2, [R0, #0x40]
        SUBS    R1, R1, #1
        BNE     loop
        SVC     #10
"""))
    model = LabSimModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    elapsed = time.perf_counter() - start
    assert model.board.leds == 1 and model.update()
    assert elapsed < 5.0, f"{elapsed:.3f} s"
