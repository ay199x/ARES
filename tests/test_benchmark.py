# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Speed targets: a loop of 10,000,000 instructions runs in under 2 seconds, and in under
10 seconds with a tool connected."""

import json
import time

import pytest
from ares.classify import CLASSES, FORMATS
from ares.gui.tools.counter import CounterModel
from ares.gui.tools.mmio import KeyboardDisplayModel
from ares.machine import Machine, StopReason
from ares.runner import Runner, State
from conftest import PROGRAMS, ROOT

BENCHMARK = PROGRAMS / "loop10m.s"
TARGET_SECONDS = 2.0
TOOL_SECONDS = 10.0             # with any one tool connected (about 1 s with the counter)


@pytest.mark.serial
def test_ten_million_instructions_at_full_speed(build):
    machine = Machine(build(BENCHMARK.read_text()))
    start = time.perf_counter()
    reason = machine.run()
    elapsed = time.perf_counter() - start
    assert reason is StopReason.EXIT
    assert machine.console.text.startswith("0xa9596240\n")
    assert elapsed < TARGET_SECONDS, f"{elapsed:.3f} s"


@pytest.mark.serial
def test_ten_million_instructions_through_go(build):
    """The same through the Runner, the path the window and the command line use."""
    runner = Runner(Machine(build(BENCHMARK.read_text())))
    start = time.perf_counter()
    assert runner.run() is State.FINISHED
    elapsed = time.perf_counter() - start
    assert runner.machine.console.text.startswith("0xa9596240\n")
    assert elapsed < TARGET_SECONDS, f"{elapsed:.3f} s"


@pytest.mark.serial
def test_ten_million_instructions_with_the_dynamic_instruction_counter(build):
    """Connected, the counter counts per basic block: DynARMic's counts in both panels, in
    time."""
    machine = Machine(build(BENCHMARK.read_text()))
    model = CounterModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    expected = json.loads((ROOT / "tests" / "data" / "dynarmic" / "loop10m.json").read_text())
    assert model.total == expected["instructions"] == 10_000_009
    assert dict(zip(FORMATS, model.formats)) == expected["formats"]
    assert dict(zip(CLASSES, model.classes)) == expected["classes"]
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s"


@pytest.mark.serial
def test_ten_million_instructions_with_the_keyboard_and_display(build):
    """Connected, the Keyboard and Display MMIO Simulator adds no hook: the JTAG UART tells
    it what the program writes (the benchmark writes only through system calls)."""
    machine = Machine(build(BENCHMARK.read_text()))
    model = KeyboardDisplayModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    assert machine.console.text.startswith("0xa9596240\n") and model.display.text == ""
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s"
