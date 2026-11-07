# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The BHT Simulator's window: its lists, table, fields, colours and log."""

import time

import pytest
from conftest import native, press_key
from test_gui_assemble import assemble
from test_gui_look import RETURN_KEYS, tab_cycle
from test_gui_run import go_to_end, loaded, max_speed, slow
from test_responsiveness import pictures

from ares.gui.tools import bht
from ares.gui.tools.bht import (FIELDS, LOG_LIMIT, NEXT_COLOUR, RIGHT_COLOUR, WRONG_COLOUR,
                                BHTWindow, log_line)
from ares.gui.widgets import bars_needed
from ares.runner import State
from ares.gui.tools.frame import paragraphs

LOOP = """\
        .global _start
_start: LDR     R0, ={count}
loop:   SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
"""
BNE = "BNE #4"
TWO_LOOPS = """\
        .global _start
_start: LDR     R0, ={first}
one:    SUBS    R0, R0, #1
        BNE     one
        LDR     R0, ={second}
two:    SUBS    R0, R0, #1
        BNE     two
        SVC     #10
"""
FOREVER = """\
        .global _start
_start: ADD     R0, R0, #1
        CMP     R0, #0
        BNE     _start
"""


def simulator(app):
    """Open the BHT Simulator (or bring it to the front); returns its window."""
    app.run("tool_bht")
    return app.tool_windows["tool_bht"]


def connected(app):
    window = simulator(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def fields(window):
    return {label: window.fields[label].get() for label in FIELDS}


def row(window, index):
    """(cells, colour) of a row of the table."""
    shown = window.table.row(index)
    return shown.cells, shown.background


def log_lines(window):
    return window.log.get("1.0", "end-1c").splitlines()


def choose(window, number, value):
    """Choose a value in one of the lists, as a click in its drop-down does."""
    chooser = window.lists[number]
    chooser.set(value)
    chooser.event_generate("<<ComboboxSelected>>")


def test_it_opens_from_the_tools_menu(app, hidden_windows):
    menu = app._menu_items["tool_bht"][0]
    assert menu.entrycget(app._menu_items["tool_bht"][1], "state") == "normal"
    menu.invoke(app._menu_items["tool_bht"][1])
    window = app.tool_windows["tool_bht"]
    assert isinstance(window, BHTWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "BHT Simulator"
    assert [chooser.get() for chooser in window.lists] == ["16", "1", "Not taken"]
    assert [list(chooser.cget("values")) for chooser in window.lists] == [
        ["8", "16", "32"], ["1", "2"], ["Not taken", "Taken"]]
    assert all(str(chooser.cget("state")) == "readonly" for chooser in window.lists)
    assert window.table.count == 16
    assert [column.heading for column in window.table.columns] == [
        "Index", "History", "Prediction", "Correct", "Incorrect", "Accuracy"]
    assert row(window, 5) == (("5", "NT", "Not taken", "0", "0", ""), "")
    assert fields(window) == dict.fromkeys(FIELDS, "") | {"Branches": "0"}
    assert log_lines(window) == []
    assert hidden_windows.focus is window.connect_button


def test_steps_colour_the_entry_of_the_branch(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    app.run("step")                             # LDR: no branch yet
    assert fields(window)["Instruction"] == "" and row(window, 2)[1] == ""
    app.run("step")                             # SUBS: BNE runs next
    assert row(window, 2) == (("2", "NT", "Not taken", "0", "0", ""), NEXT_COLOUR)
    assert fields(window) == {"Instruction": BNE, "Address": "0x00000008", "Index": "2",
                              "Branches": "0", "Accuracy": ""}
    assert log_lines(window) == []
    app.run("step")                             # BNE taken, predicted not taken
    assert row(window, 2) == (("2", "T", "Taken", "0", "1", "0.00%"), WRONG_COLOUR)
    assert fields(window) == {"Instruction": BNE, "Address": "0x00000008", "Index": "2",
                              "Branches": "1", "Accuracy": "0.00%"}
    assert log_lines(window) == [
        "BNE #4 at 0x00000008, index 2: predicted not taken, was taken (incorrect)"]
    app.run("step")                             # SUBS: the next branch is coloured
    assert row(window, 2)[1] == NEXT_COLOUR
    app.run("step")                             # BNE taken, predicted taken
    assert row(window, 2) == (("2", "T", "Taken", "1", "1", "50.00%"), RIGHT_COLOUR)
    assert len(log_lines(window)) == 2
    app.run("backstep")                         # BNE runs next again; the table keeps it
    assert row(window, 2) == (("2", "T", "Taken", "1", "1", "50.00%"), NEXT_COLOUR)
    assert fields(window)["Branches"] == "2"
    assert all(row(window, index)[1] == "" for index in range(16) if index != 2)


def test_go_to_the_end(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    go_to_end(app)
    assert row(window, 2) == (("2", "NT", "Not taken", "1", "2", "33.33%"), WRONG_COLOUR)
    assert fields(window) == {"Instruction": BNE, "Address": "0x00000008", "Index": "2",
                              "Branches": "3", "Accuracy": "33.33%"}
    assert log_lines(window)[1:] == [
        "BNE #4 at 0x00000008, index 2: predicted taken, was taken (correct)",
        "BNE #4 at 0x00000008, index 2: predicted taken, was not taken (incorrect)"]


def test_the_next_branch_is_coloured_while_the_window_shows_the_next_instruction(app,
                                                                                tmp_path):
    """Not while the program races at full speed, nor once it has ended. The runner is
    driven as the window drives it between the slices of a run."""
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    for _ in range(4):
        app.run("step")                         # LDR, SUBS, BNE, SUBS: BNE runs next
    assert window._focus[2] == NEXT_COLOUR
    runner = app.runner
    max_speed(app)
    runner.go()
    window.refresh()
    assert runner.state is State.RUNNING and window._focus[2] == WRONG_COLOUR
    slow(app, 30)                               # a slow run shows each next instruction
    window.refresh()
    assert window._focus[2] == NEXT_COLOUR
    max_speed(app)
    runner.pause()
    window.refresh()
    assert runner.state is State.PAUSED and window._focus[2] == NEXT_COLOUR
    app.run("stop")
    assert window._focus[2] == WRONG_COLOUR


def test_new_settings_start_the_table_again(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    go_to_end(app)
    choose(window, 1, "1")                      # the value it has: nothing changes
    assert fields(window)["Branches"] == "3" and len(log_lines(window)) == 3
    choose(window, 0, "8")
    assert window.table.count == 8 and window.model.entries == 8
    assert fields(window) == dict.fromkeys(FIELDS, "") | {"Branches": "0"}
    assert log_lines(window) == [] and window.model.connected
    choose(window, 1, "2")
    choose(window, 2, "Taken")
    assert row(window, 2) == (("2", "T, T", "Taken", "0", "0", ""), "")
    app.run("reset")
    go_to_end(app)
    assert row(window, 2) == (("2", "T, NT", "Taken", "2", "1", "66.67%"), WRONG_COLOUR)
    choose(window, 0, "32")
    assert window.table.count == 32 and row(window, 31)[0][1:3] == ("T, T", "Taken")


def test_the_reset_button(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    go_to_end(app)
    window.reset_button.invoke()
    assert row(window, 2) == (("2", "NT", "Not taken", "0", "0", ""), "")
    assert fields(window)["Branches"] == "0" and log_lines(window) == []
    assert window.model.connected and [c.get() for c in window.lists] == ["16", "1", "Not taken"]
    app.run("reset")
    go_to_end(app)
    assert fields(window)["Branches"] == "3" and len(log_lines(window)) == 3


def test_assemble_reset_and_closing_the_file_keep_the_table(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    go_to_end(app)
    app.run("reset")                            # Reset (F12)
    assert fields(window)["Branches"] == "3"
    assemble(app)                               # a new program: still connected
    assert window.model.connected and window.model.machine is app.machine
    go_to_end(app)
    assert fields(window)["Branches"] == "6" and len(log_lines(window)) == 6
    app.run("close")
    assert window.model.connected and window.model.machine is None
    assert fields(window)["Branches"] == "6" and row(window, 2)[1] == WRONG_COLOUR
    loaded(app, tmp_path, LOOP.format(count=2), "other.s")
    go_to_end(app)
    assert fields(window)["Branches"] == "8"


def test_close_disconnects(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    window.close_button.invoke()
    assert window.window is None
    assert not window.model.connected and not app.machine.observers.active
    go_to_end(app)
    again = simulator(app)
    assert not again.model.connected and fields(again)["Branches"] == "0"


def test_the_log_keeps_the_newest_lines(app, tmp_path):
    loaded(app, tmp_path, LOOP.format(count=LOG_LIMIT + 5))
    window = connected(app)
    app.run("step")
    for _ in range(4):                          # SUBS, BNE: two lines before the run
        app.run("step")
    assert len(log_lines(window)) == 2
    go_to_end(app)
    lines = log_lines(window)
    assert len(lines) == LOG_LIMIT and fields(window)["Branches"] == str(LOG_LIMIT + 5)
    assert lines[-1].endswith("was not taken (incorrect)")
    assert all(line.endswith("was taken (correct)") for line in lines[:-1])


def test_the_log_keeps_the_newest_lines_when_they_come_in_parts(app, tmp_path):
    """Lines added at a breakpoint, at the end of the run and at a Step, each time fewer
    than LOG_LIMIT: once the log has more, its oldest lines go."""
    loaded(app, tmp_path, TWO_LOOPS.format(first=600, second=600))
    app.execute.text_segment.toggle_breakpoint(0xC)         # the LDR after the first loop
    window = connected(app)
    go_to_end(app)                                          # 600 branches
    assert app.runner.state is State.PAUSED and len(log_lines(window)) == 600
    go_to_end(app)                                          # 600 more: the newest 1,000 stay
    lines = log_lines(window)
    assert [line.split(" at ")[0] for line in lines] == [BNE] * 400 + ["BNE #0x10"] * 600
    assert lines == [log_line(event) for event in window.model.log]
    app.run("reset")
    for _ in range(3):                                      # LDR, SUBS, BNE: one line more
        app.run("step")
    lines = log_lines(window)
    assert len(lines) == LOG_LIMIT and lines == [log_line(event) for event in window.model.log]
    assert lines[-1] == f"{BNE} at 0x00000008, index 2: predicted not taken, was taken (incorrect)"


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_in_the_table_and_the_lists_presses_connect(app, key):
    window = simulator(app)
    press_key(window.table.body, key)
    assert window.model.connected
    press_key(window.lists[0], key)
    assert not window.model.connected


def test_tab_goes_round_the_lists_the_table_the_log_and_the_buttons(app):
    """Tab and Shift+Tab never stay in the log."""
    window = simulator(app)
    native(window.window)
    connect = window.connect_button
    stops = [window.reset_button, window.close_button, *window.lists,
             window.table.body, window.log]
    assert tab_cycle(connect) == stops + [connect]
    assert tab_cycle(connect, back=True) == stops[::-1] + [connect]


@pytest.mark.parametrize("entries", bht.ENTRIES)
def test_the_table_has_room_for_16_rows_and_every_column(app, entries):
    """The room the table gets inside its border and under its headings, as the table
    decides its scroll bars: up to 16 entries need none, 32 the vertical one only."""
    window = simulator(app)
    choose(window, 0, str(entries))
    table = window.table
    holder = table.master
    border = 2 * table.winfo_pixels(table.cget("borderwidth"))
    width = int(holder.cget("width")) - border
    height = int(holder.cget("height")) - border - int(table.header.cget("height"))
    least = sum(column.base for column in table.columns)
    assert bars_needed(lambda room: entries <= room // table.row_height,
                       lambda room: least <= room, width, height,
                       (table.vscroll.winfo_reqwidth(), table.hscroll.winfo_reqheight())) == (
        entries > 16, False)
    assert height // table.row_height == bht.VISIBLE_ROWS == 16


def test_the_help_text(app):
    window = simulator(app)
    text = paragraphs(window.HELP)
    for words in ("Number of entries", "History bits", "Initial prediction", "BNE", "Reset",
                  "light yellow", "1,000"):
        assert words in text, words
    assert "\n\n" in text


def test_no_pictures_are_made_for_the_bht_simulator(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, LOOP.format(count=3))
    window = connected(app)
    app.run("step")
    go_to_end(app)
    choose(window, 0, "32")
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


@pytest.mark.serial
def test_the_log_waits_while_the_program_races(app, tmp_path):
    """At full speed the table and the fields follow each slice, the log the end of the run.
    The slices run as the window runs them."""
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    max_speed(app)
    runner = app.runner
    runner.go()
    while window.model.executed <= LOG_LIMIT:
        runner.run_slice()
        window.refresh()
    executed = str(window.model.executed)
    assert window.fields["Branches"].get() == executed == str(sum(window.model.counts[2]))
    assert log_lines(window) == []
    runner.pause()
    start = time.perf_counter()
    window.refresh()
    assert time.perf_counter() - start < 0.2    # 1,000 lines at once, without a stall
    lines = log_lines(window)
    assert len(lines) == LOG_LIMIT and lines[-1].startswith("BNE #0 at 0x00000008, index 2")
    assert window.fields["Branches"].get() == executed


def test_the_module_names_its_window():
    assert bht.WINDOW is BHTWindow and BHTWindow.MODEL is bht.BHTModel
