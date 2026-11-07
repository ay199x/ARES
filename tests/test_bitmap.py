# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Bitmap Display's model: the words it shows, its settings, and what it observes."""

import time

import pytest
from conftest import PROGRAMS

from ares.gui.tools.bitmap import (DATA, HEAP, BitmapModel, bands, data_start, fits,
                                   parse_address, ppm, zoom)
from ares.machine import DDR_END, Machine, StopReason
from ares.runner import Runner

SMALL = {"unit_width": 8, "unit_height": 8, "width": 64, "height": 64}     # 8 x 8 units
RED, GREEN, BLUE, YELLOW = 0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00

PICTURE = """\
        .data
screen: .word   0x00FF0000, 0x0000FF00      @ red, green: the first two units
        .space  62 * 4
        .global _start
        .text
_start: LDR     R1, =screen
        LDR     R0, =0x000000FF             @ blue
        STR     R0, [R1, #8]                @ the third unit
        STR     R0, [R1, #4 * 8]            @ the first unit of the second row
        MOV     R0, #0
        STR     R0, [R1]                    @ the first unit black again
        SVC     #10
"""
HEAP_PICTURE = """\
        .data
color:  .word   0x00FFFF00                  @ yellow
        .global _start
        .text
_start: MOV     R0, #256                    @ bytes for 64 units
        SVC     #9                          @ R0 = their address, the start of the heap
        LDR     R1, =color
        LDR     R1, [R1]
        STR     R1, [R0, #4]                @ the second unit
        SVC     #10
"""
TYPED = 0x00100000
TYPED_PICTURE = """\
        .global _start
        .text
_start: LDR     R1, =0x00100000
        LDR     R0, =0x00FFFFFF             @ white
        STR     R0, [R1, #4 * 9]            @ row 1, column 1
        STRB    R0, [R1, #4 * 63]           @ only the blue byte of the last unit
        SVC     #10
"""
READ_STRING = """\
        .data
screen: .space  64 * 4
        .global _start
        .text
_start: LDR     R0, =screen
        MOV     R1, #16
        SVC     #8                          @ read a string into the first units
        SVC     #10
"""


def small(machine=None, base=DATA):
    """A connected model of 8 x 8 units of 8 x 8 pixels, observing machine."""
    model = BitmapModel()
    assert model.set_layout(**SMALL) and model.set_base(base)
    model.connect(machine)
    return model


def make(build, source=PICTURE):
    machine = Machine(build(source))
    return machine, Runner(machine)


def colors(model, row):
    return [model.color(column, row) for column in range(model.columns)]


# Reading what the user types and what the window draws --------------------------------

@pytest.mark.parametrize("text, address", [
    ("0x00100000", 0x00100000), ("0X1F0", 0x1F0), (" 0x40 ", 0x40), ("1048576", 0x100000),
    ("0", 0), ("0x0", 0), ("007", 7), ("0x00000000000000010", 0x10)])
def test_a_typed_address(text, address):
    assert parse_address(text) == address


@pytest.mark.parametrize("text", ["", "0x", "abc", "-4", "+4", "1.5", "0x1_0", "1e3", "0x 10",
                                  "0x1" + "0" * 10, "9" * 11, "١٢"])
def test_not_an_address(text):
    assert parse_address(text) is None


def test_what_fits():
    assert fits(0, 4) and fits(DDR_END - 4, 4) and fits(0x100000, 512 * 256 * 4)
    assert not fits(2, 4) and not fits(DDR_END - 4, 8) and not fits(DDR_END, 4)
    assert not fits(-4, 4)


def test_a_ppm_picture_of_words():
    words = bytes([0x01, 0x02, 0x03, 0xAA,      # 0xAA030201: the top byte does not matter
                   0xFF, 0x00, 0x00, 0x00,      # blue
                   0x00, 0x00, 0xFF, 0x00,      # red
                   0x00, 0xFF, 0x00, 0x00])     # green
    assert ppm(words, 2, 1, 1) == (b"P6\n2 2\n255\n" + bytes([3, 2, 1, 0, 0, 255,
                                                              255, 0, 0, 0, 255, 0]))
    big = ppm(words, 2, 3, 2)                   # each word 3 x 2 pixels
    header = b"P6\n6 4\n255\n"
    assert big.startswith(header)
    pixels = big[len(header):]
    row = lambda first, second: bytes(first) * 3 + bytes(second) * 3   # noqa: E731
    assert pixels == (row((3, 2, 1), (0, 0, 255)) * 2 + row((255, 0, 0), (0, 255, 0)) * 2)


def test_runs_of_rows():
    assert bands([]) == []
    assert bands([3]) == [(3, 4)]
    assert bands([0, 1, 2, 5, 7, 8]) == [(0, 3), (5, 6), (7, 9)]
    assert bands(list(range(0, 40, 2)), most=16) == [(0, 39)]       # 20 runs: one band


def test_screen_pixels_per_pixel():
    assert zoom(1.0, 512, 256, 1152, 756) == 1
    assert zoom(1.4985, 512, 256, 1536, 1008) == 1          # 150 %: whole pixels only
    assert zoom(2.25, 512, 256, 2304, 1512) == 2
    assert zoom(2.25, 1024, 1024, 2304, 1512) == 1          # 2048 would not fit
    assert zoom(3.0, 1024, 512, 2304, 1512) == 2
    assert zoom(2.25, 1024, 1024, 700, 700) == 1            # never below 1


# The words it shows ---------------------------------------------------------------

def test_the_defaults():
    model = BitmapModel()
    assert (model.unit_width, model.unit_height, model.width, model.height) == (1, 1, 512, 256)
    assert (model.columns, model.rows, model.base) == (512, 256, DATA)
    assert model.words == bytes(512 * 256 * 4) and model.size == len(model.words)
    assert not model.connected and model.address() is None
    assert model.take_changes() == list(range(256))         # all of it, black, at first
    assert model.take_changes() == []


def test_connected_it_shows_the_words_memory_holds(build):
    machine, runner = make(build)
    model = small(machine)
    assert model.address() == data_start(machine.program)
    assert colors(model, 0)[:3] == [RED, GREEN, 0]          # the program's first values
    assert model.take_changes() == list(range(8))
    runner.step()
    runner.step()
    assert not model.update() and model.take_changes() == []     # nothing in the display
    runner.step()                                           # STR R0, [R1, #8]
    assert model.update() and model.color(2, 0) == BLUE
    assert model.take_changes() == [0]
    runner.step()
    assert model.update() and model.color(0, 1) == BLUE and model.take_changes() == [1]
    runner.run()
    model.update()
    assert colors(model, 0)[:3] == [0, GREEN, BLUE] and model.take_changes() == [0]
    assert model.words == machine.read_memory(model.address(), model.size)


def test_backstep_and_reset_show_the_words_put_back(build):
    machine, runner = make(build)
    model = small(machine)
    for _ in range(6):
        runner.step()                                       # up to the black unit
    model.update()
    assert model.color(0, 0) == 0
    model.take_changes()
    runner.backstep()                                       # memory gets red back
    assert model.update() and model.color(0, 0) == RED and model.take_changes() == [0]
    runner.run()
    runner.reset()                                          # the program's first values
    assert model.update() and model.take_changes() == [0, 1]
    assert colors(model, 0)[:3] == [RED, GREEN, 0] and model.color(0, 1) == 0


def test_words_written_by_a_system_call_show(make_runner):
    runner = make_runner(READ_STRING, input_text="ABCDEFG\n")
    model = small(runner.machine)
    runner.run()
    assert model.update()
    typed = runner.machine.read_memory(model.address(), 8)
    assert typed.startswith(b"ABCDEFG")
    assert model.color(0, 0) == int.from_bytes(b"ABC", "little")
    assert model.color(1, 0) == int.from_bytes(typed[4:7], "little")


def test_the_heap_and_a_typed_address(build):
    machine, runner = make(build, HEAP_PICTURE)
    model = small(machine, HEAP)
    assert model.address() == machine.heap_start != data_start(machine.program)
    runner.run()
    model.update()
    assert colors(model, 0)[:3] == [0, YELLOW, 0]
    machine, runner = make(build, TYPED_PICTURE)
    model = small(machine, TYPED)
    assert model.address() == TYPED
    runner.run()
    model.update()
    assert model.color(1, 1) == 0xFFFFFF
    assert model.color(7, 7) == 0x0000FF                    # STRB: the blue byte alone


def test_a_wrong_base_address_keeps_the_old(build):
    model = small()
    for wrong in (TYPED + 2, DDR_END - 4, DDR_END, DDR_END - model.size + 4):
        assert not model.set_base(wrong) and model.base == DATA
    assert model.set_base(DDR_END - model.size) and model.base == DDR_END - model.size
    # A larger display would reach past DDR3 from there: refused, the sizes stay.
    assert not model.set_layout(1, 1, 64, 64)
    assert (model.unit_width, model.width, model.columns) == (8, 64, 8)
    assert model.set_layout(16, 16, 64, 64) and model.columns == 4          # smaller: fits


def test_settings_show_the_display_anew(build):
    machine, runner = make(build)
    model = small(machine)
    runner.run()
    model.update()
    model.take_changes()
    assert model.set_layout(8, 8, 64, 64) and model.take_changes() == []    # the same
    assert model.set_layout(8, 16, 64, 64)                  # taller units: 8 x 4 of them
    assert model.rows == 4 and model.take_changes() == [0, 1, 2, 3]
    assert colors(model, 0)[:3] == [0, GREEN, BLUE] and model.color(0, 1) == BLUE
    assert model.set_layout(8, 8, 128, 64)                  # 16 x 8: the words flow on
    assert model.take_changes() == list(range(8))
    assert colors(model, 0)[:9] == [0, GREEN, BLUE, 0, 0, 0, 0, 0, BLUE]
    assert model.set_base(HEAP) and model.address() == machine.heap_start
    assert model.take_changes() == list(range(8)) and set(model.words) == {0}


def test_nothing_is_observed_while_disconnected(build):
    machine, runner = make(build)
    model = BitmapModel()
    assert model.set_layout(**SMALL)
    model.observe(machine)                  # not connected: the program is not observed
    assert model.machine is None and not model.update() and set(model.words) == {0}
    model.connect(machine)
    assert colors(model, 0)[:2] == [RED, GREEN]
    model.disconnect()
    runner.run()
    assert not model.update() and colors(model, 0)[:3] == [RED, GREEN, 0]   # it stays
    model.take_changes()
    assert model.set_layout(8, 8, 128, 64)  # nothing observed to draw: black
    assert set(model.words) == {0} and model.take_changes() == list(range(8))
    model.connect(machine)
    assert colors(model, 0)[:3] == [0, GREEN, BLUE]         # as memory holds them now


def test_reset_draws_the_display_again(build):
    model = small(Machine(build(PICTURE)))
    model.take_changes()
    model.reset()                           # from memory: the same words, every row anew
    assert colors(model, 0)[:2] == [RED, GREEN] and model.take_changes() == list(range(8))
    model.disconnect()
    model.reset()                           # nothing observed: black
    assert set(model.words) == {0} and model.take_changes() == list(range(8))


def test_it_follows_the_program_across_assemble_and_closing_its_file(build):
    machine, runner = make(build)
    model = small(machine)
    runner.run()
    other = Machine(build(HEAP_PICTURE))    # a new Assemble: the window passes the new machine
    model.observe(other)
    assert model.machine is other and model.address() == data_start(other.program)
    assert model.color(0, 0) == YELLOW and model.color(1, 0) == 0
    model.observe(None)                     # its file closed: connected, the picture stays
    assert model.connected and model.address() is None and not model.update()
    assert model.color(0, 0) == YELLOW
    model.reset()                           # no program to draw from: black
    assert set(model.words) == {0}
    model.observe(machine)
    assert colors(model, 0)[:3] == [0, GREEN, BLUE]


def test_connected_it_adds_no_hook(build):
    machine, runner = make(build)
    hooks = len(machine.uc._callbacks)
    model = small(machine)
    assert model.connected and not machine.observers.active
    assert len(machine.uc._callbacks) == hooks
    runner.reset()
    assert len(machine.uc._callbacks) == hooks


def test_a_program_without_data_starts_its_display_at_its_end(build):
    machine = Machine(build(TYPED_PICTURE))
    end = max(section.end for section in machine.program.sections)
    assert data_start(machine.program) == (end + 3) & ~3 == machine.heap_start


def test_a_display_reaching_past_ddr3_shows_black_there(build):
    model = small(Machine(build(PICTURE)))
    model.base = DDR_END - 4 * 8            # as if a place were there: the first row only
    model.reset()
    assert model.words == bytes(model.size)


@pytest.mark.serial
def test_ten_million_instructions_with_the_bitmap_display(build):
    """Connected, the display reads its words once per refresh and adds nothing per
    instruction: the benchmark's word in .data shows its final value."""
    machine = Machine(build((PROGRAMS / "loop10m.s").read_text()))
    model = BitmapModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    assert model.color(0, 0) == 0xA9596240 & 0xFFFFFF       # the sum, without its top byte
    assert elapsed < 10.0, f"{elapsed:.3f} s"
