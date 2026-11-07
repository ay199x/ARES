# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The programs of examples/: each runs to its expected output, in the house style."""

import pytest
from conftest import ROOT

from ares import classify, xray
from ares.assembler import assemble
from ares.capitals import offences
from ares.console import FINISHED
from ares.gui.tools.bht import BHTModel
from ares.gui.tools.bitmap import BitmapModel
from ares.gui.tools.cache import CacheModel
from ares.gui.tools.counter import CounterModel
from ares.gui.tools.labsim import LabSimModel
from ares.machine import Machine
from ares.program import Program
from ares.runner import Runner, State

EXAMPLES = ROOT / "examples"
# file -> (what is typed, what Run I/O shows before the end line)
EXPECTED = {
    "hello.s": ("", "Hello, world!\n"),
    "arithmetic.s": ("", "1 + 2 + ... + 10 = 55\n5 factorial = 120\n"),
    "arrays.s": ("", "Sum: 89\nLargest: 31\n"),
    "strings.s": ("ARM\n3\n", "A word: Letters: 3\nHow many times? ARM ARM ARM \n"),
    "functions.s": ("", "6 factorial = 720\n"),
    "floats.s": ("", "Area: 19.634954\nOne third: 0.3333333333333333\n"),
    "jtag_uart.s": ("", "Hello from the JTAG UART\n"),
    "bitmap_display.s": ("", ""),
    "lab_sim.s": ("", ""),
    "keyboard_echo.s": ("Abc1\n", "ABC1\n"),
    "cache_walk.s": ("", "Total: 32640\n"),
    "branches.s": ("", "Odd numbers: 64\n"),
    "sorting.s": ("", "3 7 19 24 42 56 71 88 \n"),
    "instruction_mix.s": ("", "Result: 78\n"),
    "float_bits.s": ("", "0x3f800000\n0xbf000000\n0x3dcccccd\n"),
    "xray_tour.s": ("", ""),
}


def source(name):
    return (EXAMPLES / name).read_text(encoding="utf-8")


def loaded(name, tmp_path):
    result = assemble(source(name), tmp_path)
    assert result.ok, [message.format() for message in result.messages]
    return Machine(Program(result.elf_path))


def run_with(model, name, tmp_path):
    """Run an example with a tool's model connected; the stopped machine."""
    machine = loaded(name, tmp_path)
    model.connect(machine)
    assert Runner(machine).run() is State.FINISHED
    model.update()
    return machine


def test_every_example_is_listed():
    assert sorted(path.name for path in EXAMPLES.glob("*.s")) == sorted(EXPECTED)


def test_the_main_subjects_are_covered():
    for name in ("hello.s", "arithmetic.s", "arrays.s", "strings.s", "functions.s", "floats.s",
                 "jtag_uart.s"):
        assert name in EXPECTED
    assert "PUSH" in source("functions.s") and "POP" in source("functions.s")
    assert "SVC     #8" in source("strings.s") and "SVC     #5" in source("strings.s")
    assert ".float" in source("floats.s") and ".double" in source("floats.s")


@pytest.mark.parametrize("name", EXPECTED)
def test_an_example_gives_its_output(name, tmp_path):
    typed, output = EXPECTED[name]
    machine = loaded(name, tmp_path)
    machine.console.feed(typed)
    assert machine.run(time_limit=20) is not None
    assert machine.console.text == f"{output}{FINISHED}\n"


@pytest.mark.parametrize("name", EXPECTED)
def test_an_example_is_in_the_house_style(name, tmp_path):
    text = source(name)
    assert offences(text) == []
    lines = text.split("\n")
    assert lines[0] == "@ SPDX-License-Identifier: GPL-2.0-or-later"
    assert lines[1] == "@ Copyright (c) 2026 The ARES Project"
    assert lines[3].startswith("@ ")            # says what it does
    assert ".global _start" in text and ".text" in text
    if ".data" in text:
        assert text.index(".data") < text.index(".global _start")
    assert text.index(".global _start") < text.index(".text")
    assert assemble(text, tmp_path).messages == []


@pytest.mark.parametrize("name", EXPECTED)
def test_an_example_is_short_and_commented(name):
    lines = source(name).split("\n")
    assert len(lines) <= 80
    assert all(len(line) <= 100 for line in lines)
    assert sum("@" in line for line in lines) >= 5


def test_the_jtag_example_uses_no_system_call_and_would_run_on_cpulator():
    code = [line.split("@")[0] for line in source("jtag_uart.s").split("\n")]
    assert not any("SVC" in line for line in code)
    assert any("B       ." in line for line in code)


def test_the_bitmap_example_draws_its_picture(tmp_path):
    model = BitmapModel()
    run_with(model, "bitmap_display.s", tmp_path)
    assert (model.columns, model.rows) == (512, 256)    # the tool's settings as they are
    assert model.color(0, 0) == 0xFFFFFF        # the diagonal
    assert model.color(200, 100) == 0xFFFFFF
    assert model.color(511, 0) == 0xFF0000      # red at the top right
    assert model.color(1, 255) == 0x00FF00      # green at the bottom left


def test_the_lab_sim_example_lights_the_board(tmp_path):
    model = LabSimModel()
    model.board.flip(3)
    run_with(model, "lab_sim.s", tmp_path)
    assert model.board.segments(0) == 0x6F      # 9
    assert model.board.leds == 0b1000           # the switch that is up


def test_the_cache_example_is_fast_by_rows_and_slow_by_columns(tmp_path):
    model = CacheModel()
    run_with(model, "cache_walk.s", tmp_path)
    accesses = model.hits + model.misses
    # 256 stores by rows at 3 hits in 4, 256 loads by columns at none, and a few constants.
    assert 256 + 256 <= accesses <= 256 + 256 + 8
    assert 180 <= model.hits <= 200


def test_the_branch_example_gives_the_table_work(tmp_path):
    model = BHTModel()
    run_with(model, "branches.s", tmp_path)
    correct = sum(counts[1] for counts in model.counts)
    wrong = sum(counts[0] for counts in model.counts)
    assert correct + wrong == 8 + 8 * 16 + 8 * 16
    assert wrong > 100 and correct > 100


def test_the_xray_example_stays_inside_the_datapath_and_returns_with_bx(tmp_path):
    machine = loaded("xray_tour.s", tmp_path)
    runner = Runner(machine)
    seen, returns = set(), 0
    while runner.state is not State.FINISHED:
        word = machine.peek_words(machine.pc, 1)[0]
        assert xray.outside_note(word) == "", hex(word)
        seen.add(xray.decode(word).kind)
        returns += word == 0xE12FFF1E
        runner.step()
    assert returns == 1
    assert seen >= {xray.DP_REGISTER, xray.DP_IMMEDIATE, xray.LOAD_IMMEDIATE, xray.LOAD_REGISTER,
                    xray.STORE_IMMEDIATE, xray.BRANCH, xray.BRANCH_LINK, xray.BRANCH_EXCHANGE}
    assert machine.reg(5) == 46 and machine.reg(3) == 9
    total = machine.program.label_address("total")
    assert machine.peek_words(total, 2) == [23, 9]


def test_the_xray_example_has_no_instruction_outside_the_datapath_in_its_text(tmp_path):
    code = [line.split("@")[0] for line in source("xray_tour.s").split("\n")]
    assert not any(word in line for line in code for word in ("SVC", "PUSH", "POP", "LDM", "STM"))


def test_the_mix_example_fills_both_panels(tmp_path):
    model = CounterModel()
    run_with(model, "instruction_mix.s", tmp_path)
    assert all(model.classes), dict(zip(classify.CLASSES, model.classes))
    assert all(model.formats), dict(zip(classify.FORMATS, model.formats))
