# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Keyboard and Display MMIO Simulator's model: what the program writes to the JTAG
UART, the display's grid after a bell, the keys typed, and what survives Assemble and Reset.

Most tests give the model the JTAG UART's reports themselves (Uart); the others run
programs that store to the JTAG UART.
"""

import pytest

from ares.gui.tools.mmio import BATCH, COLUMNS, LIMIT, ROWS, KeyboardDisplayModel
from ares.machine import Machine
from ares.observers import Observers
from ares.runner import Runner, State

PRINT = """\
        .data
text:   .asciz  "Hi\\n"
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        LDR     R1, =text
next:   LDRB    R2, [R1], #1
        CMP     R2, #0
        BEQ     done
        STRB    R2, [R0]
        B       next
done:   SVC     #10
"""
# Stores each word of the list to the JTAG UART's data register (STR: all 32 bits).
WORDS = """\
        .data
words:  .word   {words}, 0xFFFFFFFF
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        LDR     R1, =words
next:   LDR     R2, [R1], #4
        CMN     R2, #1
        BEQ     done
        STR     R2, [R0]
        B       next
done:   SVC     #10
"""
SPACES = " " * COLUMNS


def bell(x, y):
    """The word that moves the display's cursor to column x of row y."""
    return x << 20 | y << 8 | 7


class Uart:
    """Stands for a machine whose JTAG UART reports what the program stores to it."""

    def __init__(self):
        self.observers = Observers()

    def write(self, *values):
        for value in values:
            for _, callback in self.observers.jtag:
                callback(value)

    def text(self, text):
        self.write(*text.encode("utf-8"))


def connected(machine=None):
    """(model, uart): a model connected to machine, or to a Uart."""
    machine = machine if machine is not None else Uart()
    model = KeyboardDisplayModel()
    model.connect(machine)
    return model, machine


def rows(model):
    return model.display.text.split("\n")


# The JTAG UART's watchers -----------------------------------------------------

def test_the_jtag_uart_reports_what_is_stored_to_its_data_register(build):
    """Bytes and words, with all their bits; the control register and the data register's
    other bytes are not output, and are not reported."""
    machine = Machine(build(WORDS.format(words="0x41, 0x12345642")))
    seen = []
    assert machine.observers.jtag == [] and not machine.observers.active
    machine.observers.watch_jtag("tool", seen.append)
    assert machine.observers.active
    runner = Runner(machine)
    runner.run()
    assert seen == [0x41, 0x12345642] and machine.console.text.startswith("AB")
    runner.reset()                              # one Observers per machine: still watched
    runner.run()
    assert seen == [0x41, 0x12345642] * 2
    machine.observers.forget("tool")
    assert machine.observers.jtag == [] and not machine.observers.active
    runner.reset()
    runner.run()
    assert len(seen) == 4


def test_only_the_data_register_is_reported(build):
    machine = Machine(build(".global _start\n_start: LDR R0, =0xFF201000\n"
                            "        MOV R1, #'A'\n        STR R1, [R0, #4]\n"
                            "        STRB R1, [R0, #1]\n        STRB R1, [R0]\n        SVC #10\n"))
    seen = []
    machine.observers.watch_jtag("tool", seen.append)
    Runner(machine).run()
    assert seen == [0x41] and machine.console.text.startswith("A\n")


def test_an_error_in_a_jtag_watcher_stops_the_run(build):
    machine = Machine(build(PRINT))

    def broken(value):
        raise ValueError("the tool failed")
    machine.observers.watch_jtag("tool", broken)
    with pytest.raises(ValueError, match="the tool failed"):
        Runner(machine).run()
    assert machine.stop_reason is None


# The display ---------------------------------------------------------------------

def test_the_display_shows_what_the_program_writes_to_the_jtag_uart(build):
    machine = Machine(build(PRINT))
    model, _ = connected(machine)
    assert Runner(machine).run() is State.FINISHED
    assert model.update() and not model.update()            # nothing new the second time
    assert model.display.text == "Hi\n"
    assert machine.console.text == "Hi\n-- program is finished running --\n"   # Run I/O too
    assert model.grid is None and model.cursor is None


def test_system_calls_print_only_to_run_io(build):
    machine = Machine(build(".data\nt: .asciz \"by SVC\"\n.global _start\n.text\n"
                            "_start: LDR R0, =t\n        SVC #4\n        SVC #10\n"))
    model, _ = connected(machine)
    Runner(machine).run()
    assert not model.update() and model.display.text == ""
    assert machine.console.text.startswith("by SVC")


def test_nothing_is_observed_while_disconnected(build):
    machine = Machine(build(PRINT))
    runner = Runner(machine)
    model = KeyboardDisplayModel()
    model.observe(machine)                      # not connected: the program is not observed
    assert model.machine is None and not machine.observers.active
    runner.run()
    model.connect(machine)
    assert machine.observers.jtag != [] and model.display.text == ""
    runner.reset()
    runner.run()
    model.disconnect()                          # takes in what came before
    assert model.display.text == "Hi\n" and not machine.observers.active
    runner.reset()
    runner.run()
    assert not model.update() and model.display.text == "Hi\n"


def test_utf8_characters_and_zero_bytes():
    """As Run I/O shows them: UTF-8, also across updates; a zero byte shows nothing."""
    model, uart = connected()
    uart.write(0xC3)
    model.update()
    uart.write(0xA9, 0, 0x21, 0xFF, 0x41)
    model.update()
    assert model.display.text == "é!�A"


def test_the_output_of_each_program_starts_afresh():
    """As in Run I/O: the first bytes of a character the last program did not finish are
    not joined to the next program's output."""
    model, uart = connected()
    uart.write(0xC3)
    other = Uart()
    model.observe(other)                        # a new Assemble
    other.write(0x41)
    model.update()
    assert model.display.text == "A"


def test_a_form_feed_clears_the_display():
    model, uart = connected()
    uart.text("old\n")
    uart.write(12)
    uart.text("new")
    model.update()
    assert model.display.text == "new" and model.grid is None


def test_the_display_keeps_the_newest_characters():
    """Past LIMIT characters the oldest go, down to 90,000: the next 10,000 characters drop
    nothing, so the window does not take text away at every refresh."""
    model, uart = connected()
    uart.text(("a" * 39 + "\n") * (LIMIT // 40 - 1))        # 40 characters short of LIMIT
    model.update()
    assert model.display.dropped == 0
    uart.text("b" * 100)                                    # a line and a part of the next
    model.update()
    text, added = model.display.text, LIMIT - 40 + 101
    assert len(text) == LIMIT * 9 // 10 == 90_000
    assert text.endswith("a\n" + "b" * COLUMNS + "\n" + "b" * 36)
    assert model.display.added == added and model.display.dropped == added - len(text)
    dropped = model.display.dropped
    uart.text("\n" + ("c" * 39 + "\n") * 249 + "c" * 39)    # 10,000 more: LIMIT in all, kept
    model.update()
    assert len(model.display.text) == LIMIT and model.display.dropped == dropped
    uart.text("d")                                          # one past LIMIT: cut again
    model.update()
    text = model.display.text
    assert len(text) == 90_000 and text.endswith("c" * 39 + "\n" + "c" * 39 + "d")
    assert model.display.dropped == model.display.added - len(text)


def test_long_lines_are_broken_at_the_last_column():
    """As the display wraps them, so that the window's text has no long lines (Tk lays out
    a long line it wraps itself slowly): a line break goes before a character that would
    go past the last column, also across updates; a tab goes on to the next multiple of 8."""
    model, uart = connected()
    uart.text("a" * COLUMNS + "\n")                 # a full line keeps its own line break
    uart.text("b" * (COLUMNS + 1))
    model.update()
    uart.text("c" * 2 * COLUMNS)
    model.update()
    assert rows(model) == ["a" * COLUMNS, "b" * COLUMNS, "b" + "c" * (COLUMNS - 1),
                           "c" * COLUMNS, "c"]
    uart.text("\n" + "x" * 60 + "\tab\n\t" + "y" * 60 + "\n" + "w" * COLUMNS + "\tv")
    model.update()
    assert rows(model)[-6:] == ["x" * 60 + "\t", "ab", "\t" + "y" * 56, "y" * 4,
                                "w" * COLUMNS, "\tv"]
    uart.text("z" * 50)
    uart.write(12)                                  # a form feed: the next line is new
    uart.text("d" * (COLUMNS + 1))
    model.update()
    assert rows(model) == ["d" * COLUMNS, "d"]
    uart.text("\n" + "e" * COLUMNS + "\r\nf")     # a return before a line feed: no column
    model.update()
    assert rows(model)[-2:] == ["e" * COLUMNS, "f"]


def test_typed_keys_are_broken_at_the_last_column():
    model = KeyboardDisplayModel()
    model.typed("k" * (COLUMNS + 1))
    assert model.keyboard.text == "k" * COLUMNS + "\nk"
    model.typed("\b")                               # the key goes, not the line break
    assert model.keyboard.text == "k" * COLUMNS
    model.typed("\bz" + "m" * COLUMNS)
    assert model.keyboard.text == "k" * (COLUMNS - 1) + "z\n" + "m" * COLUMNS
    model.reset()
    model.typed("n" * 3)
    assert model.keyboard.text == "nnn"


def test_writes_are_taken_in_batches():
    """The values waiting are taken in once there are BATCH of them; update() still
    reports that the display changed."""
    model, uart = connected()
    text = ("x" * 31 + "\n") * (BATCH // 32)
    uart.text(text)
    assert model.display.text == text
    assert model.update() and not model.update()


# The display as a grid (after a bell) ----------------------------------------------

def test_a_bell_turns_the_display_into_a_grid():
    model, uart = connected()
    uart.text("plain text goes")
    uart.write(bell(3, 2))
    uart.text("XY")
    model.update()
    lines = rows(model)
    assert len(lines) == ROWS and all(len(line) == COLUMNS for line in lines)
    assert lines[2] == "   XY" + " " * (COLUMNS - 5)
    assert all(line == SPACES for index, line in enumerate(lines) if index != 2)
    assert model.cursor == (5, 2)
    uart.write(bell(0, 0))                      # a later bell only moves the cursor
    uart.text("Z")
    model.update()
    assert rows(model)[2].startswith("   XY ") and rows(model)[0].startswith("Z ")


def test_a_position_past_the_edge_goes_to_the_last_column_or_row():
    model, uart = connected()
    uart.write(bell(4000, 1), bell(2, 300))
    model.update()
    assert model.cursor == (2, ROWS - 1)
    uart.write(bell(256, 256))                  # all 12 bits of each count
    model.update()
    assert model.cursor == (COLUMNS - 1, ROWS - 1)
    uart.write(bell(COLUMNS, ROWS))
    model.update()
    assert model.cursor == (COLUMNS - 1, ROWS - 1)
    uart.write(7)                               # a byte: column 0, row 0
    model.update()
    assert model.cursor == (0, 0)


def test_characters_go_on_in_the_next_row_and_stay_in_the_last_cell():
    model, uart = connected()
    uart.write(bell(COLUMNS - 2, 0))
    uart.text("abc")
    model.update()
    assert rows(model)[0].endswith(" ab") and rows(model)[1].startswith("c ")
    assert model.cursor == (1, 1)
    uart.write(bell(COLUMNS - 2, ROWS - 1))
    uart.text("ab")
    model.update()
    assert model.cursor == (COLUMNS - 1, ROWS - 1)          # nothing comes after the last cell
    uart.text("cd")
    model.update()
    assert rows(model)[-1].endswith(" ad") and model.cursor == (COLUMNS - 1, ROWS - 1)


def test_line_feed_return_tab_and_backspace_move_the_cursor_on_the_grid():
    model, uart = connected()
    uart.write(bell(5, 3))
    uart.text("\n")
    model.update()
    assert model.cursor == (0, 4)
    uart.text("ab\r")
    model.update()
    assert model.cursor == (0, 4)
    uart.text("\tc\t\t")
    model.update()
    assert rows(model)[4] == "ab      c" + " " * (COLUMNS - 9) and model.cursor == (24, 4)
    uart.text("\b\bd")
    model.update()
    assert rows(model)[4][22] == "d" and model.cursor == (23, 4)
    uart.write(bell(0, ROWS - 1))
    uart.text("e\nf")
    model.update()
    assert rows(model)[-1].startswith("f ") and model.cursor == (1, ROWS - 1)
    uart.write(bell(COLUMNS - 1, 0))
    uart.text("g\t\bh")
    model.update()
    assert rows(model)[0].endswith("h") and model.cursor == (0, 1)
    uart.write(bell(0, 1))
    uart.text("\bi")                            # a BackSpace in column 0 stays there
    model.update()
    assert rows(model)[1].startswith("i ") and model.cursor == (1, 1)


def test_other_characters_take_a_cell():
    model, uart = connected()
    uart.write(bell(0, 0))
    uart.write(0x1B, 0)
    uart.text("é")
    model.update()
    assert rows(model)[0].startswith("\x1bé ") and model.cursor == (2, 0)


def test_a_form_feed_fills_the_grid_with_spaces():
    model, uart = connected()
    uart.write(bell(9, 9))
    uart.text("abc")
    uart.write(12)
    model.update()
    assert rows(model) == [SPACES] * ROWS and model.cursor == (0, 0)


# The keyboard -------------------------------------------------------------------------

def test_typed_keys_show_in_the_keyboard_area():
    model = KeyboardDisplayModel()
    model.typed("ab")
    version = model.keyboard.version
    model.typed("\b")                           # takes the last character away
    assert model.keyboard.text == "a" and model.keyboard.version != version
    model.typed("c\n\t\bd\ud83d")               # half a pair: as the program gets it
    assert model.keyboard.text == "ac\nd?"
    model.typed("\b" * 9)
    assert model.keyboard.text == ""


# Reset, Assemble, Backstep -----------------------------------------------------------

def test_reset_clears_both_areas_and_ends_the_grid():
    model, uart = connected()
    uart.write(bell(1, 1))
    uart.text("a")
    model.update()
    model.typed("keys")
    uart.text("not shown")                      # written before the Reset button was pressed
    model.reset()
    assert (model.display.text, model.keyboard.text, model.grid, model.cursor) == (
        "", "", None, None)
    assert model.connected
    uart.text("after")
    model.update()
    assert model.display.text == "after"


def test_the_display_stays_across_reset_backstep_and_assemble(build):
    machine = Machine(build(PRINT))
    runner = Runner(machine)
    model, _ = connected(machine)
    for _ in range(6):                          # up to the STRB of "H"
        runner.step()
    runner.backstep()                           # what was written stays written
    model.update()
    assert model.display.text == "H"
    runner.reset()                              # Reset (F12): the display stays
    runner.run()
    model.update()
    assert model.display.text == "HHi\n"
    other = Machine(build(WORDS.format(words=bell(1, 0))))
    model.observe(other)                        # a new Assemble: still connected
    assert not machine.observers.active and model.machine is other
    Runner(other).run()
    model.update()
    assert model.cursor == (1, 0)
    model.observe(None)                         # the program's file closed: still connected
    assert model.connected and not other.observers.active and model.cursor == (1, 0)


def test_a_word_moves_the_cursor_from_a_program(build):
    machine = Machine(build(WORDS.format(words=f"{bell(10, 4)}, 0x4F, 0x4B")))
    model, _ = connected(machine)
    Runner(machine).run()
    model.update()
    assert rows(model)[4][10:12] == "OK" and model.cursor == (12, 4)
    assert machine.console.text.startswith("\x07OK")        # Run I/O gets the low bytes


def test_a_return_shows_nothing_even_apart_from_its_line_feed():
    model, uart = connected()
    uart.text("=" * COLUMNS + "\r")
    model.update()
    uart.text("\nEND\r\n")
    model.update()
    assert model.display.text == "=" * COLUMNS + "\nEND\n"
